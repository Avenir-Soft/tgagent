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
from src.telegram.models import TelegramAccount, TelegramDiscussionGroup

logger = logging.getLogger(__name__)


class TelegramClientManager:
    """Manages Telethon client instances per tenant."""

    # How long to wait for more messages before processing (seconds).
    # Users often type "ока" + "айфон" + "15" as 3 quick messages —
    # we batch them into "ока айфон 15" → single AI request → single response.
    # 3.5s is enough for most fast typers (type + send takes ~2-3s per message).
    DEBOUNCE_DELAY = 3.5
    # Max messages to buffer before forcing processing (safety limit)
    MAX_BUFFER_SIZE = 8

    def __init__(self):
        self._clients: dict[UUID, object] = {}  # tenant_id -> TelethonClient
        self._running = False
        # Per-conversation processing lock — ensures one AI call at a time
        self._conversation_locks: dict[int, asyncio.Lock] = {}
        # Message batching: buffer incoming texts + debounce timer
        self._message_buffers: dict[int, list[tuple]] = {}  # chat_id -> [(event, text), ...]
        self._debounce_tasks: dict[int, asyncio.Task] = {}  # chat_id -> timer task
        self._tenant_for_chat: dict[int, UUID] = {}  # chat_id -> tenant_id

    async def start_client(self, account: TelegramAccount) -> None:
        """Start a Telethon client for a specific tenant account."""
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

        # Start typing immediately on first message
        client = self._clients.get(tenant_id)
        if client and len(self._message_buffers[chat_id]) == 1:
            try:
                await client.action(chat_id, 'typing')
            except Exception:
                pass

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
                else:
                    if tg_username and conversation.telegram_username != tg_username:
                        conversation.telegram_username = tg_username
                    if full_name and conversation.telegram_first_name != full_name:
                        conversation.telegram_first_name = full_name

                # Save ALL individual inbound messages to DB (for chat history)
                for ev, text in events_and_texts:
                    msg = Message(
                        tenant_id=tenant_id,
                        conversation_id=conversation.id,
                        telegram_message_id=ev.id,
                        direction="inbound",
                        sender_type="customer",
                        raw_text=text,
                        normalized_text=text.strip().lower(),
                    )
                    db.add(msg)
                await db.flush()

                # Update conversation timestamp
                from datetime import datetime, timezone
                conversation.last_message_at = datetime.now(timezone.utc)
                await db.commit()

                # Combine all texts into one message for AI
                combined_text = " ".join(text for _, text in events_and_texts)
                if len(events_and_texts) > 1:
                    logger.info(
                        "Batched %d messages for chat %s: %r",
                        len(events_and_texts), chat_id, combined_text
                    )

                # Dispatch to AI if enabled
                if conversation.ai_enabled:
                    from src.ai.orchestrator import process_dm_message

                    # Start typing indicator while AI processes
                    client = self._clients.get(tenant_id)
                    typing_task = None
                    if client:
                        async def _keep_typing():
                            try:
                                while True:
                                    await client.action(chat_id, 'typing')
                                    await asyncio.sleep(4)
                            except asyncio.CancelledError:
                                pass
                            except Exception:
                                pass
                        typing_task = asyncio.create_task(_keep_typing())

                    response_text = await process_dm_message(
                        tenant_id=tenant_id,
                        conversation_id=conversation.id,
                        user_message=combined_text,
                        db=db,
                    )

                    # Stop typing
                    if typing_task:
                        typing_task.cancel()
                        try:
                            await typing_task
                        except asyncio.CancelledError:
                            pass

                    if response_text:
                        delay = min(max(len(response_text) * 0.02, 1.0), 5.0)
                        await asyncio.sleep(delay)
                        sent = await last_event.respond(response_text)
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

            except Exception:
                logger.exception("Error handling DM for tenant %s", tenant_id)
                await db.rollback()

    async def _handle_comment(self, tenant_id: UUID, event) -> None:
        """Handle comment in discussion group — match triggers, reply with template."""
        async with async_session_factory() as db:
            try:
                text = (event.raw_text or "").strip().lower()
                if not text:
                    return

                # Check if this group is tracked for this tenant
                chat = await event.get_chat()
                result = await db.execute(
                    select(TelegramDiscussionGroup).where(
                        TelegramDiscussionGroup.tenant_id == tenant_id,
                        TelegramDiscussionGroup.telegram_group_id == chat.id,
                        TelegramDiscussionGroup.is_active.is_(True),
                    )
                )
                if not result.scalar_one_or_none():
                    return

                # Load templates
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

                        # Log as audit
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
                        break  # only reply once per comment

            except Exception:
                logger.exception("Error handling comment for tenant %s", tenant_id)
                await db.rollback()

    @staticmethod
    def _matches_trigger(text: str, trigger_type: str, patterns: list | dict) -> bool:
        """Check if message text matches any trigger pattern."""
        if isinstance(patterns, dict):
            patterns = patterns.get("patterns", [])

        for pattern in patterns:
            pattern_lower = str(pattern).strip().lower()
            if trigger_type == "keyword":
                if pattern_lower in text:
                    return True
            elif trigger_type == "emoji":
                if pattern in text:
                    return True
            elif trigger_type == "regex":
                if re.search(pattern, text, re.IGNORECASE):
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
