"""Instagram event handler — processes DMs and comments.

Mirrors the Telegram service pattern: buffer → debounce → AI processing.
Reuses the same AI orchestrator (process_dm_message) and truth_tools.

Two modes:
  1. Official Meta Graph API (webhook-based) — client.py
  2. instagrapi (polling-based) — client_instagrapi.py  ← ACTIVE for demo

When official developer account is ready, swap _USE_INSTAGRAPI = False.
"""

import asyncio
import logging
import random
import re
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.conversations.models import Conversation, Message
from src.core.database import async_session_factory
# ── Official Meta API (uncomment when developer account ready) ──────
# from src.instagram.client import InstagramApiClient
# ── instagrapi (temporary for demo) ─────────────────────────────────
from src.instagram.client_instagrapi import InstagrapiClient, LoginRequiredError
from src.instagram.models import InstagramAccount
from src.leads.models import Lead
from src.sse.event_bus import publish_event

logger = logging.getLogger(__name__)

# Debounce: buffer rapid messages before AI processing
_DEBOUNCE_SECONDS = 3.5
_MAX_BUFFER = 8

# Polling intervals for instagrapi mode
_DM_POLL_INTERVAL = 30      # seconds between DM checks (30s to avoid API ban)
_COMMENT_POLL_INTERVAL = 120  # seconds between comment checks (2min to avoid API ban)


class InstagramManager:
    """Manages Instagram API clients and event handling per tenant."""

    def __init__(self):
        self._clients: dict[UUID, object] = {}              # tenant_id → client (either type)
        self._accounts: dict[UUID, InstagramAccount] = {}   # tenant_id → account obj
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._message_buffers: dict[str, list] = {}         # ig_user_id → [(text, timestamp)]
        self._debounce_tasks: dict[str, asyncio.Task] = {}
        self._comment_hints: dict[str, dict] = {}           # ig_user_id → product hint
        self._dedup: dict[str, float] = {}                  # msg_id → timestamp
        self._polling_tasks: dict[UUID, list[asyncio.Task]] = {}  # instagrapi polling
        self._seen_dm_ids: set[str] = set()                 # dedup for polling
        self._seen_comment_ids: set[str] = set()

    # ── Client Management ────────────────────────────────────────────────

    async def start_client(self, account: InstagramAccount) -> None:
        """Initialize official API client for an Instagram account."""
        from src.instagram.client import InstagramApiClient
        if not account.access_token:
            logger.warning("No access_token for IG account %s", account.instagram_username)
            return
        client = InstagramApiClient(
            access_token=account.access_token,
            ig_user_id=account.instagram_user_id,
            page_id=account.facebook_page_id,
        )
        self._clients[account.tenant_id] = client
        self._accounts[account.tenant_id] = account
        logger.info("Instagram client (official) started for tenant=%s @%s",
                     account.tenant_id, account.instagram_username)

    async def start_instagrapi(
        self, tenant_id: UUID, username: str, password: str = "", session_id: str = "",
        proxy: str = "",
    ) -> None:
        """Start instagrapi client with DM/comment polling."""
        client = InstagrapiClient(username, password=password, session_id=session_id, proxy=proxy)
        await client.login()
        self._clients[tenant_id] = client

        # Pre-fill seen IDs so we don't process old messages on first poll
        await self._init_seen_ids(client)

        # Start polling loops
        dm_task = asyncio.create_task(self._poll_dm_loop(tenant_id))
        comment_task = asyncio.create_task(self._poll_comments_loop(tenant_id))
        self._polling_tasks[tenant_id] = [dm_task, comment_task]

        logger.info("Instagram client (instagrapi) started for @%s, polling active", username)

    async def stop_client(self, tenant_id: UUID) -> None:
        # Cancel polling tasks
        for task in self._polling_tasks.pop(tenant_id, []):
            task.cancel()
        client = self._clients.pop(tenant_id, None)
        self._accounts.pop(tenant_id, None)
        if client:
            await client.close()

    def get_client(self, tenant_id: UUID):
        return self._clients.get(tenant_id)

    def get_account(self, tenant_id: UUID) -> InstagramAccount | None:
        return self._accounts.get(tenant_id)

    # ── Webhook Event Dispatch ───────────────────────────────────────────

    async def handle_webhook_event(self, entry: dict) -> None:
        """Dispatch a single webhook entry to DM or comment handler."""
        # DM events
        for msg_event in entry.get("messaging", []):
            await self._on_dm_event(msg_event)

        # Comment events (via changes field)
        for change in entry.get("changes", []):
            if change.get("field") == "comments":
                await self._on_comment_event(change.get("value", {}))

    # ── DM Handling ──────────────────────────────────────────────────────

    async def _on_dm_event(self, event: dict) -> None:
        """Handle incoming DM webhook event — buffer and debounce."""
        sender_id = event.get("sender", {}).get("id")
        message = event.get("message", {})
        msg_text = message.get("text", "")
        msg_id = message.get("mid", "")

        if not sender_id or not msg_text:
            return

        # Find tenant for this IG account
        recipient_id = event.get("recipient", {}).get("id")
        tenant_id = self._find_tenant_by_ig_user_id(recipient_id)
        if not tenant_id:
            logger.warning("No tenant found for IG user_id=%s", recipient_id)
            return

        # Skip own messages (echo)
        account = self._accounts.get(tenant_id)
        if account and sender_id == account.instagram_user_id:
            return

        # Dedup
        now = time.monotonic()
        if msg_id and msg_id in self._dedup:
            return
        if msg_id:
            self._dedup[msg_id] = now
            # Clean old dedup entries (>60s)
            stale = [k for k, v in self._dedup.items() if now - v > 60]
            for k in stale:
                del self._dedup[k]

        # Buffer for debounce
        buf_key = f"{tenant_id}:{sender_id}"
        buf = self._message_buffers.setdefault(buf_key, [])
        buf.append({"text": msg_text, "sender_id": sender_id, "tenant_id": tenant_id,
                     "timestamp": event.get("timestamp", 0), "attachments": message.get("attachments", [])})

        # Cancel existing debounce, start new
        existing = self._debounce_tasks.get(buf_key)
        if existing and not existing.done():
            existing.cancel()

        if len(buf) >= _MAX_BUFFER:
            self._debounce_tasks[buf_key] = asyncio.create_task(self._flush_dm_buffer(buf_key))
        else:
            self._debounce_tasks[buf_key] = asyncio.create_task(self._debounce_flush(buf_key))

    async def _debounce_flush(self, buf_key: str) -> None:
        await asyncio.sleep(_DEBOUNCE_SECONDS)
        await self._flush_dm_buffer(buf_key)

    async def _flush_dm_buffer(self, buf_key: str) -> None:
        """Process buffered DM messages through AI pipeline."""
        messages = self._message_buffers.pop(buf_key, [])
        if not messages:
            return

        tenant_id = messages[0]["tenant_id"]
        sender_id = messages[0]["sender_id"]
        combined_text = "\n".join(m["text"] for m in messages if m.get("text"))

        # Check for photo attachments
        photo_url = None
        for m in messages:
            for att in m.get("attachments", []):
                if att.get("type") == "image":
                    photo_url = att.get("payload", {}).get("url")
                    break

        # Per-conversation lock
        lock_key = f"ig:{tenant_id}:{sender_id}"
        lock = self._conversation_locks.setdefault(lock_key, asyncio.Lock())

        async with lock:
            await self._process_dm(tenant_id, sender_id, combined_text, photo_url)

    async def _process_dm(
        self, tenant_id: UUID, sender_id: str, text: str, photo_url: str | None,
    ) -> None:
        """Process a DM through the AI pipeline and send response."""
        from src.ai.orchestrator import process_dm_message
        from src.ai.models import AiSettings

        client = self._clients.get(tenant_id)
        if not client:
            logger.error("No IG client for tenant=%s", tenant_id)
            return

        async with async_session_factory() as db:
            try:
                # Check AI settings
                ai_result = await db.execute(
                    select(AiSettings).where(AiSettings.tenant_id == tenant_id)
                )
                ai_settings = ai_result.scalar_one_or_none()
                if ai_settings and not getattr(ai_settings, "allow_auto_instagram_dm_reply", True):
                    return

                # Find or create conversation
                conv_result = await db.execute(
                    select(Conversation).where(
                        Conversation.tenant_id == tenant_id,
                        Conversation.instagram_user_id == sender_id,
                        Conversation.source_type.in_(["instagram_dm", "dm"]),
                    )
                )
                conversation = conv_result.scalar_one_or_none()

                if not conversation:
                    # Get user profile for name
                    profile = await client.get_user_profile(sender_id)
                    ig_username = profile.get("username") if profile else None
                    ig_name = profile.get("name") if profile else None

                    conversation = Conversation(
                        tenant_id=tenant_id,
                        telegram_chat_id=0,  # Not used for Instagram
                        telegram_user_id=0,
                        telegram_username=ig_username,
                        telegram_first_name=ig_name or ig_username or "Instagram User",
                        source_type="instagram_dm",
                        status="active",
                        state="NEW_CHAT",
                        instagram_user_id=sender_id,
                    )
                    db.add(conversation)
                    await db.flush()

                    # Auto-create lead
                    new_lead = Lead(
                        tenant_id=tenant_id,
                        conversation_id=conversation.id,
                        telegram_user_id=0,
                        telegram_username=ig_username,
                        customer_name=ig_name or ig_username,
                        source="instagram_dm",
                    )
                    db.add(new_lead)
                    await db.flush()

                    # SSE: new conversation
                    try:
                        await publish_event(tenant_id, "new_conversation", {
                            "conversation_id": str(conversation.id),
                            "source": "instagram",
                        })
                    except Exception:
                        pass

                # Save inbound message
                inbound_msg = Message(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    direction="inbound",
                    sender_type="customer",
                    raw_text=text,
                    ai_generated=False,
                )
                db.add(inbound_msg)
                await db.flush()

                # Check comment hints (user asked about product in comments before DMing)
                comment_hint = self._comment_hints.pop(sender_id, None)
                if comment_hint and time.monotonic() - comment_hint.get("_ts", 0) > 3600:
                    comment_hint = None

                # Download photo if attached
                customer_photo_path = None
                if photo_url:
                    import httpx, tempfile, os
                    try:
                        async with httpx.AsyncClient() as http:
                            resp = await http.get(photo_url, timeout=15)
                            if resp.status_code == 200:
                                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                                tmp.write(resp.content)
                                tmp.close()
                                customer_photo_path = tmp.name
                    except Exception as e:
                        logger.warning("Failed to download IG photo: %s", e)

                # Call AI orchestrator — SAME pipeline as Telegram
                ai_response = await process_dm_message(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    user_message=text,
                    db=db,
                    comment_hint=comment_hint,
                    customer_photo_path=customer_photo_path,
                )

                # Clean up temp photo
                if customer_photo_path:
                    import os
                    try:
                        os.unlink(customer_photo_path)
                    except Exception:
                        pass

                if not ai_response:
                    await db.commit()
                    return

                response_text = ai_response.get("text", "")
                image_urls = ai_response.get("image_urls", [])
                logger.info("IG AI response: text=%d chars, photos=%d urls=%s",
                            len(response_text), len(image_urls), image_urls[:3])

                # Send response via Instagram API (with relogin retry)
                async def _send_with_retry(send_fn, *args):
                    result = await send_fn(*args)
                    if result and result.get("error") and "login_required" in str(result.get("error", "")).lower():
                        if isinstance(client, InstagrapiClient) and await client.relogin():
                            logger.info("Relogin before send retry")
                            result = await send_fn(*args)
                    return result

                if response_text:
                    send_result = await _send_with_retry(client.send_text_message, sender_id, response_text)
                    if not send_result or send_result.get("error"):
                        logger.error("Failed to send IG DM: %s", send_result)

                # Send images — try upload, fallback to URL links
                photos_sent = False
                for img_url in image_urls[:3]:
                    img_result = await _send_with_retry(client.send_image_message, sender_id, img_url)
                    if img_result and img_result.get("error"):
                        logger.warning("IG photo upload blocked, falling back to URL link")
                        break
                    else:
                        photos_sent = True

                # Fallback: send photo URLs as text links if upload failed
                if image_urls and not photos_sent:
                    photo_links = "\n".join([f"📸 {url}" for url in image_urls[:3]])
                    link_text = f"Фото тура:\n{photo_links}"
                    await _send_with_retry(client.send_text_message, sender_id, link_text)

                # Save outbound message
                outbound_msg = Message(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    direction="outbound",
                    sender_type="ai",
                    raw_text=response_text,
                    ai_generated=True,
                )
                db.add(outbound_msg)

                # SSE: new message
                try:
                    await publish_event(tenant_id, "new_message", {
                        "conversation_id": str(conversation.id),
                        "direction": "outbound",
                        "text": response_text[:100],
                    })
                except Exception:
                    pass

                await db.commit()

            except Exception:
                logger.exception("Error processing IG DM from %s", sender_id)
                await db.rollback()

    # ── instagrapi Polling ──────────────────────────────────────────────

    async def _init_seen_ids(self, client: InstagrapiClient) -> None:
        """Pre-fill seen message/comment IDs to skip old messages on startup."""
        try:
            threads = await client.get_direct_threads(amount=20)
            for thread in threads:
                for msg in (thread.messages or [])[:5]:
                    self._seen_dm_ids.add(str(msg.id))
            logger.info("Pre-filled %d seen DM IDs", len(self._seen_dm_ids))
        except Exception as e:
            logger.warning("Failed to pre-fill seen DMs: %s", e)

        try:
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
            media_ids = await client.get_recent_media_ids(amount=5)
            for mid in media_ids:
                comments = await client.get_media_comments(mid, amount=20)
                for c in comments:
                    # Don't mark recent comments as seen — reply to them
                    c_time = getattr(c, "created_at_utc", None) or getattr(c, "created_at", None)
                    if c_time and c_time > cutoff:
                        logger.info("Skipping pre-fill for recent comment %s (%s): %s",
                                    c.pk, c_time, c.text[:30])
                        continue
                    self._seen_comment_ids.add(str(c.pk))
            logger.info("Pre-filled %d seen comment IDs (skipped recent)", len(self._seen_comment_ids))
        except Exception as e:
            logger.warning("Failed to pre-fill seen comments: %s", e)

    async def _poll_dm_loop(self, tenant_id: UUID) -> None:
        """Poll for new DMs every N seconds (instagrapi mode)."""
        backoff = _DM_POLL_INTERVAL
        consecutive_auth_failures = 0
        _MAX_AUTH_FAILURES = 5  # Stop polling after 5 consecutive 403s
        while True:
            try:
                client = self._clients.get(tenant_id)
                if not client or not isinstance(client, InstagrapiClient):
                    break

                threads = await client.get_direct_threads(amount=20)
                backoff = _DM_POLL_INTERVAL  # reset on success
                consecutive_auth_failures = 0  # reset on success

                for thread in threads:
                    for msg in (thread.messages or [])[:3]:
                        msg_id = str(msg.id)
                        if msg_id in self._seen_dm_ids:
                            continue
                        self._seen_dm_ids.add(msg_id)

                        # Skip own messages
                        if str(msg.user_id) == client.ig_user_id:
                            continue

                        # Skip non-text for now
                        if not msg.text:
                            continue

                        sender_id = str(msg.user_id)
                        logger.info("New IG DM from %s: %s", sender_id, msg.text[:50])

                        # Buffer for debounce (same as webhook path)
                        buf_key = f"{tenant_id}:{sender_id}"
                        buf = self._message_buffers.setdefault(buf_key, [])
                        buf.append({
                            "text": msg.text,
                            "sender_id": sender_id,
                            "tenant_id": tenant_id,
                            "timestamp": msg.timestamp.timestamp() if msg.timestamp else 0,
                            "attachments": [],
                        })

                        existing = self._debounce_tasks.get(buf_key)
                        if existing and not existing.done():
                            existing.cancel()

                        if len(buf) >= _MAX_BUFFER:
                            self._debounce_tasks[buf_key] = asyncio.create_task(
                                self._flush_dm_buffer(buf_key))
                        else:
                            self._debounce_tasks[buf_key] = asyncio.create_task(
                                self._debounce_flush(buf_key))

                # Cap seen set
                if len(self._seen_dm_ids) > 10000:
                    self._seen_dm_ids = set(list(self._seen_dm_ids)[-5000:])

            except asyncio.CancelledError:
                break
            except LoginRequiredError:
                consecutive_auth_failures += 1
                if consecutive_auth_failures >= _MAX_AUTH_FAILURES:
                    logger.error("IG DM poll: %d consecutive auth failures — STOPPING. Restart backend to retry.", consecutive_auth_failures)
                    break
                logger.error("IG session expired (DM) [%d/%d], attempting relogin...", consecutive_auth_failures, _MAX_AUTH_FAILURES)
                if isinstance(client, InstagrapiClient) and await client.relogin():
                    backoff = min(backoff * 2, 300) if backoff > _DM_POLL_INTERVAL else 60
                    logger.info("IG relogin successful, next poll in %ds", backoff)
                else:
                    backoff = min(backoff * 2, 300)
                    logger.error("IG relogin failed, backing off %ds", backoff)
            except Exception:
                backoff = min(backoff * 2, 120)
                logger.exception("DM poll error, backing off %ds", backoff)

            await asyncio.sleep(backoff + random.uniform(0, 3))

    async def _poll_comments_loop(self, tenant_id: UUID) -> None:
        """Poll for new comments on recent posts (instagrapi mode)."""
        backoff = _COMMENT_POLL_INTERVAL
        consecutive_auth_failures = 0
        _MAX_AUTH_FAILURES = 5
        while True:
            try:
                client = self._clients.get(tenant_id)
                if not client or not isinstance(client, InstagrapiClient):
                    break

                media_ids = await client.get_recent_media_ids(amount=5)
                logger.info("IG comment poll: found %d media, seen_comments=%d", len(media_ids), len(self._seen_comment_ids))
                for mid in media_ids:
                    comments = await client.get_media_comments(mid, amount=10)
                    logger.info("IG comment poll: media %s has %d comments", mid, len(comments))
                    for comment in comments:
                        cid = str(comment.pk)
                        if cid in self._seen_comment_ids:
                            continue
                        self._seen_comment_ids.add(cid)

                        # Skip own comments
                        if str(comment.user.pk) == client.ig_user_id:
                            continue

                        logger.info("New IG comment %s from @%s: %s", cid, comment.user.username, comment.text[:50])

                        asyncio.create_task(
                            self._process_comment(
                                tenant_id, cid, comment.text,
                                str(comment.user.pk),
                                comment.user.username,
                                mid,
                            )
                        )

                backoff = _COMMENT_POLL_INTERVAL  # reset on success
                consecutive_auth_failures = 0

                if len(self._seen_comment_ids) > 5000:
                    self._seen_comment_ids = set(list(self._seen_comment_ids)[-2000:])

            except asyncio.CancelledError:
                break
            except LoginRequiredError:
                consecutive_auth_failures += 1
                if consecutive_auth_failures >= _MAX_AUTH_FAILURES:
                    logger.error("IG comment poll: %d consecutive auth failures — STOPPING. Restart backend to retry.", consecutive_auth_failures)
                    break
                logger.error("IG session expired (comments) [%d/%d], attempting relogin...", consecutive_auth_failures, _MAX_AUTH_FAILURES)
                client = self._clients.get(tenant_id)
                if isinstance(client, InstagrapiClient) and await client.relogin():
                    backoff = min(backoff * 2, 300) if backoff > _COMMENT_POLL_INTERVAL else 60
                    logger.info("IG relogin successful (comments), next poll in %ds", backoff)
                else:
                    backoff = min(backoff * 2, 300)
                    logger.error("IG relogin failed (comments), backing off %ds", backoff)
            except Exception:
                backoff = min(backoff * 2, 120)
                logger.exception("Comment poll error, backing off %ds", backoff)

            await asyncio.sleep(backoff + random.uniform(0, 5))

    # ── Comment Handling ─────────────────────────────────────────────────

    async def _on_comment_event(self, value: dict) -> None:
        """Handle incoming comment webhook event."""
        comment_id = value.get("id")
        comment_text = value.get("text", "")
        commenter_id = value.get("from", {}).get("id")
        commenter_username = value.get("from", {}).get("username")
        media_id = value.get("media", {}).get("id")

        if not comment_id or not comment_text or not commenter_id:
            return

        # Find tenant by media owner
        tenant_id = None
        for tid, acc in self._accounts.items():
            tenant_id = tid
            break

        if not tenant_id:
            return

        # Skip own comments
        account = self._accounts.get(tenant_id)
        if account and commenter_id == account.instagram_user_id:
            return

        asyncio.create_task(
            self._process_comment(tenant_id, comment_id, comment_text,
                                   commenter_id, commenter_username, media_id)
        )

    async def _process_comment(
        self, tenant_id: UUID, comment_id: str, text: str,
        commenter_id: str, commenter_username: str | None, media_id: str | None,
    ) -> None:
        """Process a comment — smart reply with product search, template fallback, audit logging."""
        from src.ai.truth_tools import get_product_candidates
        from src.ai.models import AiSettings
        from src.conversations.models import CommentTemplate
        from src.core.audit import AuditLog

        client = self._clients.get(tenant_id)
        if not client:
            return

        async with async_session_factory() as db:
            try:
                # Check AI settings
                ai_result = await db.execute(
                    select(AiSettings).where(AiSettings.tenant_id == tenant_id)
                )
                ai_settings = ai_result.scalar_one_or_none()
                if ai_settings and not getattr(ai_settings, "allow_auto_instagram_comment_reply", True):
                    return

                # Search for products matching comment text
                search_result = await get_product_candidates(tenant_id, text, db)

                if not search_result.get("found"):
                    # No product match — try template matching before fallback
                    reply = None
                    reply_action = "ig_comment_fallback_reply"
                    template_id = None

                    tpl_result = await db.execute(
                        select(CommentTemplate).where(
                            CommentTemplate.tenant_id == tenant_id,
                            CommentTemplate.is_active.is_(True),
                            CommentTemplate.platform.in_(["all", "instagram"]),
                        )
                    )
                    templates = tpl_result.scalars().all()

                    for tpl in templates:
                        if self._matches_trigger(text.lower(), tpl.trigger_type, tpl.trigger_patterns):
                            reply = tpl.template_text
                            reply_action = "ig_comment_template_reply"
                            template_id = str(tpl.id)
                            break

                    if not reply:
                        # No template matched — hardcoded fallback
                        reply = "Assalomu alaykum! Turlar haqida ma'lumot olish uchun DM yozing."

                    await client.reply_to_comment(comment_id, reply, media_id=media_id)

                    # Audit log
                    log = AuditLog(
                        tenant_id=tenant_id,
                        actor_type="ai",
                        action=reply_action,
                        entity_type="instagram_comment",
                        meta_json={
                            "comment_id": comment_id,
                            "trigger_text": text[:300],
                            "reply_text": reply[:500],
                            "media_id": media_id,
                            "commenter_id": commenter_id,
                            "commenter_username": commenter_username,
                            "template_id": template_id,
                        },
                    )
                    db.add(log)
                    await db.commit()
                    return

                # Build smart reply with product info
                products = search_result.get("products", [])
                if products:
                    p = products[0]
                    name = p.get("name", "")
                    price_range = p.get("price_range", "")
                    seats = p.get("total_seats_available", 0)

                    reply = (
                        f"{name} — narxi {price_range} so'm, {seats} ta joy mavjud. "
                        f"Bron qilish uchun DM yozing!"
                    )
                    await client.reply_to_comment(comment_id, reply, media_id=media_id)

                    # Save comment hint for future DM context
                    self._comment_hints[commenter_id] = {
                        "product_id": p.get("product_id"),
                        "product_name": name,
                        "comment_text": text,
                        "_ts": time.monotonic(),
                    }

                    # Audit log for smart reply
                    log = AuditLog(
                        tenant_id=tenant_id,
                        actor_type="ai",
                        action="ig_comment_smart_reply",
                        entity_type="instagram_comment",
                        meta_json={
                            "comment_id": comment_id,
                            "trigger_text": text[:300],
                            "reply_text": reply[:500],
                            "media_id": media_id,
                            "commenter_id": commenter_id,
                            "commenter_username": commenter_username,
                            "products_found": len(products),
                            "product_name": name,
                        },
                    )
                    db.add(log)
                    await db.commit()

            except Exception:
                logger.exception("Error processing IG comment %s", comment_id)

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _matches_trigger(text: str, trigger_type: str, patterns: list | dict) -> bool:
        """Check if comment text matches any trigger pattern (mirrors Telegram logic)."""
        if isinstance(patterns, dict):
            patterns = patterns.get("patterns", [])

        for pattern in patterns:
            pattern_lower = str(pattern).strip().lower()
            if trigger_type == "emoji":
                if pattern in text:
                    return True
            elif trigger_type == "regex":
                if re.search(pattern, text, re.IGNORECASE):
                    return True
            else:
                # keyword, stock, price, plus, and any custom type — substring match
                if pattern_lower in text:
                    return True
        return False

    def _find_tenant_by_ig_user_id(self, ig_user_id: str | None) -> UUID | None:
        """Find tenant_id by Instagram user ID."""
        if not ig_user_id:
            return None
        for tid, acc in self._accounts.items():
            if acc.instagram_user_id == ig_user_id:
                return tid
        # Fallback: if only one tenant, use it
        if len(self._accounts) == 1:
            return next(iter(self._accounts))
        return None

    async def periodic_cleanup(self) -> None:
        """Clean up stale in-memory data (call every hour)."""
        now = time.monotonic()
        # Clean stale dedup entries
        stale_dedup = [k for k, v in self._dedup.items() if now - v > 300]
        for k in stale_dedup:
            del self._dedup[k]
        # Clean stale comment hints (>1h)
        stale_hints = [k for k, v in self._comment_hints.items()
                       if now - v.get("_ts", 0) > 3600]
        for k in stale_hints:
            del self._comment_hints[k]
        # Cap locks dict
        if len(self._conversation_locks) > 5000:
            keys = list(self._conversation_locks.keys())
            for k in keys[:len(keys) - 5000]:
                del self._conversation_locks[k]


# Global singleton
instagram_manager = InstagramManager()
