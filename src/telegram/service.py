"""Telegram integration service — manages client connections and message handling.

Each tenant has its own Telethon client. The TelegramService manages the lifecycle
of all clients and routes incoming events to the appropriate handlers.
"""

import asyncio
import logging
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import async_session_factory
from src.conversations.models import CommentTemplate, Conversation, Message
from src.leads.models import Lead
from src.telegram.models import TelegramAccount, TelegramDiscussionGroup

logger = logging.getLogger(__name__)


async def _telegram_send_with_retry(coro_factory, max_attempts=3):
    """Retry a Telegram send operation with exponential backoff.

    coro_factory: a zero-arg callable that returns a fresh awaitable each time.
    We need a factory because Telethon coroutines can't be re-awaited.
    """
    from telethon.errors import FloodWaitError
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_factory()
        except FloodWaitError as e:
            logger.warning("Telegram FloodWait %ds (attempt %d/%d)", e.seconds, attempt, max_attempts)
            await asyncio.sleep(min(e.seconds, 30))
            last_exc = e
        except (ConnectionError, OSError, TimeoutError) as e:
            logger.warning("Telegram send error (attempt %d/%d): %s", attempt, max_attempts, e)
            if attempt < max_attempts:
                await asyncio.sleep(2 ** attempt)
            last_exc = e
    raise last_exc


async def _download_photos(urls: list[str]) -> list[str]:
    """Download photo URLs to temp files. Returns list of file paths (skips failures).

    WebP images are converted to JPEG because Telegram's SendMultiMediaRequest
    (album upload) does not accept WebP — it raises MediaEmptyError.
    """
    import tempfile
    import httpx

    paths = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as http:
        for url in urls[:10]:
            try:
                resp = await http.get(url)
                if resp.status_code != 200:
                    continue
                ct = resp.headers.get("content-type", "")
                is_webp = "webp" in ct or url.lower().endswith(".webp")

                if is_webp:
                    # Convert WebP → PNG for Telegram compatibility
                    # (Telegram SendMultiMediaRequest rejects WebP; PNG preserves transparency)
                    try:
                        from PIL import Image
                        import io
                        img = Image.open(io.BytesIO(resp.content))
                        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                        img.save(tmp, format="PNG")
                        tmp.close()
                        paths.append(tmp.name)
                    except Exception:
                        logger.debug("WebP conversion failed for %s, saving as-is", url[:80])
                        tmp = tempfile.NamedTemporaryFile(suffix=".webp", delete=False)
                        tmp.write(resp.content)
                        tmp.close()
                        paths.append(tmp.name)
                else:
                    ext = ".jpg"
                    if "png" in ct:
                        ext = ".png"
                    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                    tmp.write(resp.content)
                    tmp.close()
                    paths.append(tmp.name)
            except Exception:
                logger.debug("Failed to download photo %s", url[:80], exc_info=True)
    return paths


class TelegramClientManager:
    """Manages Telethon client instances per tenant."""

    # How long to wait for more messages before processing (seconds).
    # Users often type "ока" + "айфон" + "15" as 3 quick messages —
    # we batch them into "ока айфон 15" → single AI request → single response.
    # 3.5s is enough for most fast typers (type + send takes ~2-3s per message).
    DEBOUNCE_DELAY = 3.5
    # Max messages to buffer before forcing processing (safety limit)
    MAX_BUFFER_SIZE = 8

    # Limits to prevent unbounded memory growth
    _MAX_LOCKS = 10_000
    _MAX_DEDUP = 5_000
    _MAX_HINTS = 5_000
    _CLEANUP_INTERVAL = 3600  # 1 hour

    def __init__(self):
        self._clients: dict[UUID, object] = {}  # tenant_id -> TelethonClient
        self._running = False
        # Per-conversation processing lock — ensures one AI call at a time
        self._conversation_locks: dict[int, asyncio.Lock] = {}
        # Message batching: buffer incoming texts + debounce timer
        self._message_buffers: dict[int, list[tuple]] = {}  # chat_id -> [(event, text), ...]
        self._debounce_tasks: dict[int, asyncio.Task] = {}  # chat_id -> timer task
        # Dedup: track last processed message per chat to skip exact duplicates
        self._last_processed: dict[int, tuple[str, float]] = {}  # chat_id -> (text, timestamp)
        self._tenant_for_chat: dict[int, UUID] = {}  # chat_id -> tenant_id
        # Comment→DM hints: when AI replies about a product in comments,
        # store {telegram_user_id: {product_name, product_id, variants, timestamp}}
        # so when user DMs, AI knows what product they're referring to.
        self._comment_hints: dict[int, dict] = {}  # telegram_user_id -> hint
        self._cleanup_task: asyncio.Task | None = None

    async def _periodic_cleanup(self) -> None:
        """Remove stale entries from in-memory dicts to prevent memory leak."""
        import time
        while True:
            try:
                await asyncio.sleep(self._CLEANUP_INTERVAL)
                now = time.time()

                # Clean _last_processed: remove entries older than 5 minutes
                stale_chats = [k for k, (_, ts) in self._last_processed.items() if now - ts > 300]
                for k in stale_chats:
                    self._last_processed.pop(k, None)

                # Clean _comment_hints: remove entries older than 1 hour
                stale_hints = [k for k, v in self._comment_hints.items() if now - v.get("timestamp", 0) > 3600]
                for k in stale_hints:
                    self._comment_hints.pop(k, None)

                # Cap _conversation_locks: if too many, remove unlocked ones
                if len(self._conversation_locks) > self._MAX_LOCKS:
                    unlocked = [k for k, lock in self._conversation_locks.items() if not lock.locked()]
                    for k in unlocked[:len(unlocked) // 2]:  # remove half of unlocked
                        self._conversation_locks.pop(k, None)

                # Cap _tenant_for_chat: keep only recent (we can't timestamp these, so cap by size)
                if len(self._tenant_for_chat) > self._MAX_DEDUP * 2:
                    # Keep last half by insertion order (Python 3.7+ dicts are ordered)
                    keys = list(self._tenant_for_chat.keys())
                    for k in keys[:len(keys) // 2]:
                        self._tenant_for_chat.pop(k, None)

                logger.info(
                    "Memory cleanup: locks=%d, dedup=%d, hints=%d, chat_map=%d",
                    len(self._conversation_locks), len(self._last_processed),
                    len(self._comment_hints), len(self._tenant_for_chat),
                )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in periodic cleanup")

    async def start_client(self, account: TelegramAccount) -> None:
        """Start a Telethon client for a specific tenant account."""
        # Start cleanup task if not already running
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

        try:
            from telethon import TelegramClient, events

            # Use session_ref if available, otherwise default path
            if account.session_ref:
                session_path = f"{settings.telegram_sessions_dir}/{account.session_ref}"
            else:
                session_path = f"{settings.telegram_sessions_dir}/{account.tenant_id}_{account.id}"
            client = TelegramClient(
                session_path,
                settings.telegram_api_id,
                settings.telegram_api_hash,
                device_model="AI Closer Server",
                system_version="Linux 5.15",
                app_version="1.0.0",
            )

            await client.connect()
            if not await client.is_user_authorized():
                logger.warning("Session not authorized for tenant %s, skipping", account.tenant_id)
                await client.disconnect()
                return
            self._clients[account.tenant_id] = client

            # Register event handlers
            self._register_handlers(client, account.tenant_id)

            logger.info(
                "Telegram client started for tenant %s (account %s)",
                account.tenant_id,
                account.phone_number,
            )
        except Exception:
            logger.exception("Failed to start Telegram client for tenant %s", account.tenant_id)
            raise

    def _register_handlers(self, client, tenant_id: UUID) -> None:
        from telethon import events

        @client.on(events.NewMessage(incoming=True))
        async def on_new_message(event):
            """Route incoming messages to appropriate handler."""
            chat_id = event.chat_id
            text_preview = (event.raw_text or "")[:50]
            logger.info(
                "EVENT received: chat_id=%s private=%s group=%s channel=%s text=%r",
                chat_id, event.is_private, event.is_group, event.is_channel, text_preview,
            )
            if event.is_private:
                await self._handle_dm(tenant_id, event)
            elif event.is_group or event.is_channel:
                await self._handle_comment(tenant_id, event)

    def _get_conversation_lock(self, chat_id: int) -> asyncio.Lock:
        """Get or create a per-conversation lock."""
        if chat_id not in self._conversation_locks:
            self._conversation_locks[chat_id] = asyncio.Lock()
        return self._conversation_locks[chat_id]

    async def _handle_dm(self, tenant_id: UUID, event) -> None:
        """Handle incoming DM — buffer message and debounce.

        Users often type fast and split one thought into 3-5 short messages:
          "ока" → "айфон" → "промакс" → "борми" → "15"
        Without debounce, each message triggers a separate AI call (5 API requests,
        5 responses, confusion). With debounce, we wait 2.5s for more messages,
        then combine them into "ока айфон промакс борми 15" → 1 AI call → 1 response.
        """
        chat_id = event.chat_id
        text = (event.raw_text or "").strip()

        # Handle media without text (photo, sticker, video, voice, etc.)
        if not text and event.media:
            from telethon.tl.types import (
                MessageMediaPhoto, MessageMediaDocument,
            )
            media = event.media
            if isinstance(media, MessageMediaPhoto):
                text = "[Клиент отправил фото]"
            elif isinstance(media, MessageMediaDocument):
                doc = media.document
                is_sticker = any(
                    getattr(a, 'stickerset', None) is not None
                    for a in (doc.attributes if doc else [])
                )
                is_voice = any(
                    getattr(a, 'voice', False)
                    for a in (doc.attributes if doc else [])
                )
                is_video_note = any(
                    getattr(a, 'round_message', False)
                    for a in (doc.attributes if doc else [])
                )
                if is_sticker:
                    text = "[Клиент отправил стикер]"
                elif is_voice:
                    text = "[Клиент отправил голосовое сообщение]"
                elif is_video_note:
                    text = "[Клиент отправил видеосообщение]"
                else:
                    text = "[Клиент отправил файл]"
            else:
                text = "[Клиент отправил медиа]"

        if not text:
            return

        self._tenant_for_chat[chat_id] = tenant_id

        # Add to buffer
        if chat_id not in self._message_buffers:
            self._message_buffers[chat_id] = []
        self._message_buffers[chat_id].append((event, text))
        buf_size = len(self._message_buffers[chat_id])
        logger.info("DM buffer chat=%s: +%r (total: %d)", chat_id, text, buf_size)

        # Cancel existing debounce timer
        if chat_id in self._debounce_tasks:
            self._debounce_tasks[chat_id].cancel()
            logger.info("DM debounce reset for chat=%s (waiting %.1fs more)", chat_id, self.DEBOUNCE_DELAY)

        # Get client ref for read acknowledge (typing starts later, after "reading" pause)
        client = self._clients.get(tenant_id)

        # If buffer is full, process immediately
        if len(self._message_buffers[chat_id]) >= self.MAX_BUFFER_SIZE:
            await self._flush_and_process(chat_id)
            return

        # Start new debounce timer
        self._debounce_tasks[chat_id] = asyncio.create_task(
            self._debounce_then_process(chat_id)
        )

    async def _debounce_then_process(self, chat_id: int) -> None:
        """Wait for debounce delay, then process buffered messages."""
        try:
            await asyncio.sleep(self.DEBOUNCE_DELAY)
            await self._flush_and_process(chat_id)
        except asyncio.CancelledError:
            pass  # Timer cancelled because new message arrived — will be restarted

    async def _flush_and_process(self, chat_id: int) -> None:
        """Take all buffered messages for a chat, combine them, and process as one."""
        # Pop buffer and clean up timer
        events_and_texts = self._message_buffers.pop(chat_id, [])
        self._debounce_tasks.pop(chat_id, None)

        if not events_and_texts:
            return

        tenant_id = self._tenant_for_chat.get(chat_id)
        if not tenant_id:
            return

        # Use per-conversation lock to prevent overlap with previous processing
        lock = self._get_conversation_lock(chat_id)
        async with lock:
            await self._process_batched_messages(tenant_id, chat_id, events_and_texts)

    async def _process_batched_messages(
        self, tenant_id: UUID, chat_id: int, events_and_texts: list[tuple]
    ) -> None:
        """Process a batch of messages as a single AI request."""
        async with async_session_factory() as db:
            try:
                # Use the first event for sender info, last event for responding
                first_event = events_and_texts[0][0]
                last_event = events_and_texts[-1][0]

                # Mark messages as read (double checkmark ✓✓)
                client = self._clients.get(tenant_id)
                if client:
                    try:
                        await client.send_read_acknowledge(chat_id)
                    except Exception:
                        logger.debug("Could not send read acknowledge for chat=%s", chat_id)

                sender = await first_event.get_sender()
                telegram_user_id = sender.id
                tg_username = getattr(sender, 'username', None)
                tg_first_name = getattr(sender, 'first_name', None)
                tg_last_name = getattr(sender, 'last_name', None)
                full_name = " ".join(filter(None, [tg_first_name, tg_last_name]))

                # Find or create conversation
                result = await db.execute(
                    select(Conversation).where(
                        Conversation.tenant_id == tenant_id,
                        Conversation.telegram_chat_id == chat_id,
                        Conversation.source_type == "dm",
                    )
                )
                conversation = result.scalar_one_or_none()

                if not conversation:
                    conversation = Conversation(
                        tenant_id=tenant_id,
                        telegram_chat_id=chat_id,
                        telegram_user_id=telegram_user_id,
                        telegram_username=tg_username,
                        telegram_first_name=full_name or tg_username,
                        source_type="dm",
                        status="active",
                        state="NEW_CHAT",
                    )
                    db.add(conversation)
                    await db.flush()

                    # Auto-create lead for new DM conversation
                    existing_lead_result = await db.execute(
                        select(Lead).where(
                            Lead.tenant_id == tenant_id,
                            Lead.telegram_user_id == telegram_user_id,
                        ).limit(1)
                    )
                    existing_lead = existing_lead_result.scalar_one_or_none()
                    if existing_lead:
                        existing_lead.conversation_id = conversation.id
                        if tg_username:
                            existing_lead.telegram_username = tg_username
                        if full_name:
                            existing_lead.customer_name = full_name
                        lead_for_avatar = existing_lead
                    else:
                        new_lead = Lead(
                            tenant_id=tenant_id,
                            conversation_id=conversation.id,
                            telegram_user_id=telegram_user_id,
                            telegram_username=tg_username,
                            customer_name=full_name or tg_username,
                            source="dm",
                        )
                        db.add(new_lead)
                        lead_for_avatar = new_lead
                    await db.flush()

                    # Download Telegram profile photo for lead avatar
                    if client and not lead_for_avatar.avatar_url:
                        try:
                            import os
                            avatars_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "avatars")
                            os.makedirs(avatars_dir, exist_ok=True)
                            avatar_path = os.path.join(avatars_dir, f"{lead_for_avatar.id}.jpg")
                            downloaded = await client.download_profile_photo(
                                telegram_user_id, file=avatar_path, download_big=False
                            )
                            if downloaded:
                                lead_for_avatar.avatar_url = f"/static/avatars/{lead_for_avatar.id}.jpg"
                                await db.flush()
                            elif os.path.exists(avatar_path):
                                os.remove(avatar_path)
                        except Exception:
                            logger.debug("Could not download avatar for user %s", telegram_user_id)
                else:
                    if tg_username and conversation.telegram_username != tg_username:
                        conversation.telegram_username = tg_username
                    if full_name and conversation.telegram_first_name != full_name:
                        conversation.telegram_first_name = full_name
                    # Also update lead data if username/name changed
                    if tg_username or full_name:
                        lead_result = await db.execute(
                            select(Lead).where(
                                Lead.tenant_id == tenant_id,
                                Lead.telegram_user_id == telegram_user_id,
                            ).limit(1)
                        )
                        lead = lead_result.scalar_one_or_none()
                        if lead:
                            if tg_username and lead.telegram_username != tg_username:
                                lead.telegram_username = tg_username
                            if full_name and lead.customer_name != full_name:
                                lead.customer_name = full_name

                # Save ALL individual inbound messages to DB (for chat history)
                for ev, text in events_and_texts:
                    # Detect media type and file_id
                    _media_type = None
                    _media_file_id = None
                    if ev.media:
                        from telethon.tl.types import (
                            MessageMediaPhoto, MessageMediaDocument,
                        )
                        if isinstance(ev.media, MessageMediaPhoto):
                            _media_type = "photo"
                            _media_file_id = str(ev.media.photo.id) if ev.media.photo else None
                        elif isinstance(ev.media, MessageMediaDocument) and ev.media.document:
                            doc = ev.media.document
                            _media_file_id = str(doc.id)
                            attrs = doc.attributes or []
                            is_sticker = any(getattr(a, 'stickerset', None) is not None for a in attrs)
                            is_voice = any(getattr(a, 'voice', False) for a in attrs)
                            is_video_note = any(getattr(a, 'round_message', False) for a in attrs)
                            is_gif = any(getattr(a, 'nosound', False) for a in attrs)
                            is_video = any(type(a).__name__ == 'DocumentAttributeVideo' for a in attrs) and not is_video_note and not is_gif
                            if is_sticker:
                                _media_type = "sticker"
                            elif is_voice:
                                _media_type = "voice"
                            elif is_video_note:
                                _media_type = "video_note"
                            elif is_gif:
                                _media_type = "gif"
                            elif is_video:
                                _media_type = "video"
                            else:
                                _media_type = "document"

                    msg = Message(
                        tenant_id=tenant_id,
                        conversation_id=conversation.id,
                        telegram_message_id=ev.id,
                        direction="inbound",
                        sender_type="customer",
                        raw_text=text,
                        normalized_text=text.strip().lower(),
                        media_type=_media_type,
                        media_file_id=_media_file_id,
                    )
                    db.add(msg)
                await db.flush()

                # Update conversation timestamp
                from datetime import datetime, timezone
                is_new_conversation = conversation.state == "NEW_CHAT"
                conversation.last_message_at = datetime.now(timezone.utc)
                await db.commit()

                # --- SSE: notify frontend about new inbound messages ---
                try:
                    from src.sse.event_bus import publish_event
                    await publish_event(
                        f"sse:{tenant_id}:conversation:{conversation.id}",
                        {"event": "new_message", "conversation_id": str(conversation.id), "direction": "inbound"},
                    )
                    event_type = "new_conversation" if is_new_conversation else "conversation_updated"
                    await publish_event(
                        f"sse:{tenant_id}:tenant",
                        {"event": event_type, "conversation_id": str(conversation.id)},
                    )
                except Exception:
                    pass  # SSE is non-critical

                # Combine all texts into one message for AI
                combined_text = " ".join(text for _, text in events_and_texts)
                if len(events_and_texts) > 1:
                    logger.info(
                        "Batched %d messages for chat %s: %r",
                        len(events_and_texts), chat_id, combined_text
                    )

                # Check for comment→DM hint (user previously asked about a product in comments)
                import time as _time
                comment_hint = None
                hint = self._comment_hints.get(telegram_user_id)
                if hint and (_time.time() - hint.get("timestamp", 0)) < 3600:  # 1 hour TTL
                    comment_hint = hint
                    logger.info(
                        "DM HINT found: user=%s previously asked about %s in comments",
                        telegram_user_id, hint.get("product_name"),
                    )

                # Dedup: skip exact duplicate messages within 60s window
                _now = _time.time()
                _last = self._last_processed.get(chat_id)
                if _last and _last[0] == combined_text.strip().lower() and (_now - _last[1]) < 60:
                    logger.info(
                        "DEDUP: skipping duplicate message for chat=%s: %r (%.1fs since last)",
                        chat_id, combined_text[:50], _now - _last[1],
                    )
                    return
                self._last_processed[chat_id] = (combined_text.strip().lower(), _now)

                # Dispatch to AI if enabled
                if conversation.ai_enabled:
                    from src.ai.orchestrator import process_dm_message

                    # --- Human-like timing ---
                    # 1) "Reading" pause — user sees ✓✓ but no typing yet (like reading the message)
                    reading_delay = min(max(len(combined_text) * 0.06, 1.5), 3.5)
                    await asyncio.sleep(reading_delay)

                    # 2) Start typing indicator while AI processes
                    typing_task = None
                    if client:
                        async def _keep_typing():
                            from telethon.tl.functions.messages import SetTypingRequest
                            from telethon.tl.types import SendMessageTypingAction
                            try:
                                while True:
                                    await client(SetTypingRequest(chat_id, SendMessageTypingAction()))
                                    await asyncio.sleep(4)
                            except asyncio.CancelledError:
                                pass
                            except Exception:
                                pass
                        typing_task = asyncio.create_task(_keep_typing())

                    ai_result = await process_dm_message(
                        tenant_id=tenant_id,
                        conversation_id=conversation.id,
                        user_message=combined_text,
                        db=db,
                        comment_hint=comment_hint,
                    )

                    # Extract text and image URLs from result
                    if isinstance(ai_result, dict):
                        response_text = ai_result.get("text")
                        image_urls = ai_result.get("image_urls", [])
                    else:
                        response_text = ai_result
                        image_urls = []

                    # 3) "Typing" delay proportional to response length (typing stays active)
                    if response_text:
                        typing_delay = min(max(len(response_text) * 0.03, 1.0), 6.0)
                        await asyncio.sleep(typing_delay)

                    # 4) Stop typing right before sending
                    if typing_task:
                        typing_task.cancel()
                        try:
                            await typing_task
                        except asyncio.CancelledError:
                            pass

                    if response_text:
                        sent = None
                        # Send product photos if available
                        if image_urls and client:
                            photo_files = await _download_photos(image_urls[:5])
                            if photo_files:
                                try:
                                    if len(photo_files) == 1:
                                        # Single photo: caption on the photo itself
                                        if len(response_text) <= 1024:
                                            sent = await last_event.respond(
                                                response_text, file=photo_files[0]
                                            )
                                        else:
                                            photo_msg = await last_event.respond(file=photo_files[0])
                                            # Reply to photo with text
                                            sent = await photo_msg.reply(response_text)
                                    else:
                                        # Multiple photos: album, then reply to album with text
                                        album_msgs = await last_event.respond(file=photo_files)
                                        # album_msgs is a list; reply to the first photo
                                        first_album = album_msgs[0] if isinstance(album_msgs, list) else album_msgs
                                        sent = await first_album.reply(response_text)
                                except Exception:
                                    logger.warning("Failed to send photo(s), falling back to text", exc_info=True)
                                    sent = await last_event.respond(response_text)
                                finally:
                                    import os
                                    for f in photo_files:
                                        try:
                                            os.unlink(f)
                                        except OSError:
                                            pass
                            else:
                                sent = await last_event.respond(response_text)
                        else:
                            sent = await _telegram_send_with_retry(lambda: last_event.respond(response_text))

                        out_msg = Message(
                            tenant_id=tenant_id,
                            conversation_id=conversation.id,
                            telegram_message_id=sent.id if sent else None,
                            direction="outbound",
                            sender_type="ai",
                            raw_text=response_text,
                            ai_generated=True,
                        )
                        db.add(out_msg)
                        await db.commit()

                        # --- SSE: notify frontend about AI response ---
                        try:
                            from src.sse.event_bus import publish_event
                            await publish_event(
                                f"sse:{tenant_id}:conversation:{conversation.id}",
                                {
                                    "event": "new_message",
                                    "conversation_id": str(conversation.id),
                                    "direction": "outbound",
                                    "data": {
                                        "id": str(out_msg.id),
                                        "direction": "outbound",
                                        "sender_type": "ai",
                                        "raw_text": response_text,
                                        "ai_generated": True,
                                        "created_at": out_msg.created_at.isoformat() if out_msg.created_at else None,
                                    },
                                },
                            )
                            await publish_event(
                                f"sse:{tenant_id}:tenant",
                                {"event": "conversation_updated", "conversation_id": str(conversation.id)},
                            )
                        except Exception:
                            pass

            except Exception:
                logger.exception("Error handling DM for tenant %s", tenant_id)
                await db.rollback()

    async def _handle_comment(self, tenant_id: UUID, event) -> None:
        """Handle comment in discussion group — smart AI reply with product search."""
        async with async_session_factory() as db:
            try:
                raw_text = (event.raw_text or "").strip()
                text = raw_text.lower()
                if not text:
                    return

                # Check if this group is tracked for this tenant
                chat = await event.get_chat()
                logger.info(
                    "COMMENT handler: chat.id=%s chat.title=%r tenant=%s text=%r",
                    chat.id, getattr(chat, 'title', '?'), tenant_id, text[:80],
                )
                result = await db.execute(
                    select(TelegramDiscussionGroup).where(
                        TelegramDiscussionGroup.tenant_id == tenant_id,
                        TelegramDiscussionGroup.telegram_group_id == chat.id,
                        TelegramDiscussionGroup.is_active.is_(True),
                    )
                )
                group = result.scalar_one_or_none()
                if not group:
                    logger.info("COMMENT: group chat.id=%s NOT found in DB for tenant %s", chat.id, tenant_id)
                    return

                # Load AI settings
                from src.ai.models import AiSettings
                ai_result = await db.execute(
                    select(AiSettings).where(AiSettings.tenant_id == tenant_id)
                )
                ai_settings = ai_result.scalar_one_or_none()
                cta_handle = (ai_settings.channel_cta_handle if ai_settings else None) or "@avenir_uz"
                ai_replies_enabled = ai_settings.channel_ai_replies_enabled if ai_settings else True
                auto_comment_reply = ai_settings.allow_auto_comment_reply if ai_settings else True
                show_price = ai_settings.channel_show_price if ai_settings else True

                # --- Smart AI reply: search products in DB ---
                if ai_replies_enabled and auto_comment_reply:
                    smart_reply = await self._smart_comment_reply(
                        tenant_id, text, cta_handle, db, show_price=show_price
                    )
                    if smart_reply:
                        reply_text = smart_reply["text"]
                        image_url = smart_reply.get("image_url")
                        logger.info("COMMENT: smart reply for %r → %r (image=%s)", text[:40], reply_text[:60], bool(image_url))

                        if image_url:
                            photo_files = await _download_photos([image_url])
                            if photo_files:
                                try:
                                    if len(reply_text) <= 1024:
                                        await event.reply(reply_text, file=photo_files[0])
                                    else:
                                        photo_msg = await event.reply(file=photo_files[0])
                                        await photo_msg.reply(reply_text)
                                except Exception:
                                    logger.warning("Failed to send photo in comment, falling back to text", exc_info=True)
                                    await event.reply(reply_text)
                                finally:
                                    import os
                                    for f in photo_files:
                                        try:
                                            os.unlink(f)
                                        except OSError:
                                            pass
                            else:
                                await event.reply(reply_text)
                        else:
                            await event.reply(reply_text)

                        # Save comment hint for DM context
                        try:
                            sender = await event.get_sender()
                            if sender and smart_reply.get("product_id"):
                                import time as _time
                                self._comment_hints[sender.id] = {
                                    "product_id": smart_reply["product_id"],
                                    "product_name": smart_reply.get("product_name", ""),
                                    "variants_summary": smart_reply.get("variants_summary", ""),
                                    "timestamp": _time.time(),
                                    "comment_text": text[:200],
                                }
                                logger.info(
                                    "COMMENT HINT saved: user=%s → %s",
                                    sender.id, smart_reply.get("product_name"),
                                )
                        except Exception:
                            pass

                        from src.core.audit import AuditLog
                        log = AuditLog(
                            tenant_id=tenant_id,
                            actor_type="ai",
                            action="comment_smart_reply",
                            entity_type="comment",
                            meta_json={
                                "trigger_text": text[:200],
                                "chat_id": chat.id,
                                "products_found": smart_reply.get("products_count", 0),
                            },
                        )
                        db.add(log)
                        await db.commit()
                        return

                # --- Fallback: template matching ---
                result = await db.execute(
                    select(CommentTemplate).where(
                        CommentTemplate.tenant_id == tenant_id,
                        CommentTemplate.is_active.is_(True),
                    )
                )
                templates = result.scalars().all()

                for tpl in templates:
                    if self._matches_trigger(text, tpl.trigger_type, tpl.trigger_patterns):
                        await event.reply(tpl.template_text)

                        from src.core.audit import AuditLog
                        log = AuditLog(
                            tenant_id=tenant_id,
                            actor_type="ai",
                            action="comment_template_reply",
                            entity_type="comment",
                            meta_json={
                                "template_id": str(tpl.id),
                                "trigger_text": text[:200],
                                "chat_id": chat.id,
                            },
                        )
                        db.add(log)
                        await db.commit()
                        break

            except Exception:
                logger.exception("Error handling comment for tenant %s", tenant_id)
                await db.rollback()

    async def _smart_comment_reply(
        self, tenant_id: UUID, text: str, cta_handle: str, db, *, show_price: bool = True,
    ) -> dict | None:
        """Generate a teaser reply for channel comments — drives users to DM.

        When show_price=False: NO prices, NO storage/specs. Just confirm product exists + colors.
        When show_price=True: include price range from variants.
        Returns None if no products found (falls through to template matching).
        """
        from src.ai.truth_tools import get_product_candidates, get_variant_candidates
        from uuid import UUID as UUIDType

        search_result = await get_product_candidates(tenant_id, text, db)

        if not search_result.get("found"):
            return None

        products = search_result.get("products", [])
        if not products:
            return None

        first = products[0]
        product_id = UUIDType(first["product_id"])
        product_name = first["name"]
        image_url = first.get("image_url")
        in_stock = first.get("in_stock", False)

        # Get variants for colors
        variants_result = await get_variant_candidates(tenant_id, product_id, db)
        variants = variants_result.get("variants", []) if variants_result.get("found") else []

        if not image_url and variants_result.get("image_urls"):
            image_url = variants_result["image_urls"][0]

        # Collect unique colors from in-stock variants
        colors = []
        for v in variants:
            if v.get("in_stock") and v.get("color") and v["color"] not in colors:
                colors.append(v["color"])

        # Build variants summary for DM hint (not shown to user)
        variants_summary = ", ".join(
            v.get("title", "") for v in variants[:5] if v.get("in_stock")
        )

        # --- Build teaser reply ---
        lines = []

        if not in_stock:
            lines.append(f"К сожалению, {product_name} сейчас нет в наличии.")
            lines.append(f"\nНапишите в ЛС {cta_handle} — подберём альтернативу!")
            return {
                "text": "\n".join(lines), "image_url": None,
                "products_count": len(products),
                "product_id": first["product_id"], "product_name": product_name,
                "variants_summary": variants_summary,
            }

        lines.append(f"Здравствуйте! {product_name} есть в наличии ✅")

        # Show price range if enabled
        if show_price and variants:
            in_stock_prices = [v.get("price", 0) for v in variants if v.get("in_stock") and v.get("price")]
            if in_stock_prices:
                min_p, max_p = min(in_stock_prices), max(in_stock_prices)
                if min_p == max_p:
                    lines.append(f"Цена: {int(min_p):,} сум".replace(",", " "))
                else:
                    lines.append(f"Цена: от {int(min_p):,} до {int(max_p):,} сум".replace(",", " "))

        if colors:
            lines.append(f"Доступные цвета: {', '.join(colors)}")

        if len(products) > 1:
            others = [p["name"] for p in products[1:3] if p.get("in_stock")]
            if others:
                lines.append(f"Также в наличии: {', '.join(others)}")

        cta_suffix = " — оформим доставку!" if show_price else " — подскажем цену, наличие и оформим доставку!"
        lines.append(f"\nНапишите в ЛС {cta_handle}{cta_suffix}")

        return {
            "text": "\n".join(lines),
            "image_url": image_url,
            "products_count": len(products),
            "product_id": first["product_id"],
            "product_name": product_name,
            "variants_summary": variants_summary,
        }

    @staticmethod
    def _matches_trigger(text: str, trigger_type: str, patterns: list | dict) -> bool:
        """Check if message text matches any trigger pattern."""
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

    async def stop_all(self) -> None:
        for tenant_id, client in self._clients.items():
            try:
                await client.disconnect()
            except Exception:
                logger.exception("Error disconnecting client for tenant %s", tenant_id)
        self._clients.clear()

    def get_client(self, tenant_id: UUID):
        return self._clients.get(tenant_id)


# Global singleton
telegram_manager = TelegramClientManager()


async def recover_orphaned_buffers() -> int:
    """Recover message buffers that were lost during a crash. Returns count recovered."""
    recovered = 0
    for chat_id, buf in list(telegram_manager._message_buffers.items()):
        if buf and chat_id not in telegram_manager._debounce_tasks:
            logger.info("Found orphaned buffer for chat %s with %d messages", chat_id, len(buf))
            recovered += 1
            telegram_manager._message_buffers.pop(chat_id, None)
    return recovered


async def start_all_clients() -> None:
    """Start Telegram clients for all active tenants. Called on app startup."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(TelegramAccount).where(TelegramAccount.status == "connected")
        )
        accounts = result.scalars().all()
        for account in accounts:
            try:
                await telegram_manager.start_client(account)
            except Exception:
                logger.exception("Failed to start client for account %s", account.id)
