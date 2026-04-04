"""AI Closer — main FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.ai.router import router as ai_router
from src.training.router import router as training_router
from src.auth.router import router as auth_router
from src.catalog.router import router as catalog_router
from src.conversations.router import router as conversations_router
from src.dashboard.router import router as dashboard_router
from src.handoffs.router import router as handoffs_router
from src.import_data.router import router as import_router
from src.leads.router import router as leads_router
from src.orders.router import router as orders_router
from src.telegram.router import router as telegram_router
from src.tenants.router import router as tenants_router
from src.analytics.router import router as analytics_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def _run_startup_migrations():
    """Safety net: idempotent DDL for envs that haven't run Alembic yet.
    All of these are now covered by Alembic revision b2c3d4e5f6a7.
    This function can be removed once all environments have migrated."""
    from src.core.database import engine
    from sqlalchemy import text as _sql
    async with engine.begin() as conn:
        stmts = [
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS training_label VARCHAR(20)",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_training_candidate BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS rejection_selected_text TEXT",
            "ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS operator_telegram_username VARCHAR(100)",
            "ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS channel_cta_handle VARCHAR(100)",
            "ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS channel_ai_replies_enabled BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS channel_show_price BOOLEAN NOT NULL DEFAULT TRUE",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_settings_tenant ON ai_settings (tenant_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_tenant_variant ON inventory (tenant_id, variant_id)",
            "CREATE INDEX IF NOT EXISTS ix_conversations_last_msg ON conversations (last_message_at DESC NULLS LAST)",
            "CREATE INDEX IF NOT EXISTS ix_conversations_training ON conversations (is_training_candidate) WHERE is_training_candidate = TRUE",
            "CREATE INDEX IF NOT EXISTS ix_conversations_state ON conversations (state)",
            "CREATE INDEX IF NOT EXISTS ix_orders_lead ON orders (lead_id)",
            "CREATE INDEX IF NOT EXISTS ix_messages_conv_created ON messages (conversation_id, created_at DESC)",
            # Fix legacy role values
            "UPDATE users SET role = 'super_admin' WHERE role = 'admin'",
            "UPDATE users SET role = 'store_owner' WHERE role = 'owner'",
            # Analytics tables (Phase 5)
            """CREATE TABLE IF NOT EXISTS customer_segments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                lead_id UUID NOT NULL,
                customer_name VARCHAR(255),
                telegram_user_id BIGINT NOT NULL,
                recency_days INT NOT NULL DEFAULT 0,
                frequency INT NOT NULL DEFAULT 0,
                monetary NUMERIC(14,2) NOT NULL DEFAULT 0,
                r_score INT NOT NULL DEFAULT 1,
                f_score INT NOT NULL DEFAULT 1,
                m_score INT NOT NULL DEFAULT 1,
                rfm_score INT NOT NULL DEFAULT 111,
                segment VARCHAR(30) NOT NULL DEFAULT 'new',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_customer_segments_tenant_lead ON customer_segments (tenant_id, lead_id)",
            "CREATE INDEX IF NOT EXISTS ix_customer_segments_tenant_id ON customer_segments (tenant_id)",
            """CREATE TABLE IF NOT EXISTS competitor_prices (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                product_id UUID REFERENCES products(id) ON DELETE SET NULL,
                competitor_name VARCHAR(255) NOT NULL,
                competitor_channel VARCHAR(255),
                product_title VARCHAR(500) NOT NULL,
                competitor_price NUMERIC(14,2) NOT NULL,
                our_price NUMERIC(14,2),
                currency VARCHAR(10) NOT NULL DEFAULT 'UZS',
                source VARCHAR(30) NOT NULL DEFAULT 'manual',
                captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_competitor_prices_tenant_product ON competitor_prices (tenant_id, product_id)",
            "CREATE INDEX IF NOT EXISTS ix_competitor_prices_tenant_id ON competitor_prices (tenant_id)",
            # Broadcast history
            """CREATE TABLE IF NOT EXISTS broadcast_history (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                message_text TEXT NOT NULL,
                image_url TEXT,
                filter_type VARCHAR(30) NOT NULL,
                sent_count INT NOT NULL DEFAULT 0,
                failed_count INT NOT NULL DEFAULT 0,
                total_targets INT NOT NULL DEFAULT 0,
                status VARCHAR(30) NOT NULL DEFAULT 'sending',
                scheduled_at TIMESTAMPTZ,
                sent_at TIMESTAMPTZ,
                created_by_user_id UUID NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_broadcast_history_tenant ON broadcast_history (tenant_id)",
            "ALTER TABLE broadcast_history ADD COLUMN IF NOT EXISTS recipients_json JSONB",
            "ALTER TABLE broadcast_history ADD COLUMN IF NOT EXISTS target_conversation_ids JSONB",
        ]
        for stmt in stmts:
            try:
                await conn.execute(_sql(stmt))
            except Exception as e:
                logger.warning("Migration skipped (%s): %s", stmt[:50], e)


async def _execute_due_broadcasts():
    """Find and execute any scheduled broadcasts that are due."""
    from sqlalchemy import text as _sql
    from src.core.database import async_session_factory

    async with async_session_factory() as db:
        result = await db.execute(
            _sql("SELECT id, tenant_id, message_text, image_url, filter_type, created_by_user_id, target_conversation_ids FROM broadcast_history WHERE status = 'scheduled' AND scheduled_at <= now()")
        )
        due = result.fetchall()
        if not due:
            return

        for row in due:
            bid, tenant_id, msg_text, image_url, filter_type, user_id, target_conv_ids = row
            logger.info("Executing scheduled broadcast %s for tenant %s", bid, tenant_id)

            try:
                from src.telegram.service import telegram_manager
                client = telegram_manager.get_client(tenant_id)
                if not client:
                    await db.execute(_sql("UPDATE broadcast_history SET status = 'failed' WHERE id = :id"), {"id": bid})
                    await db.commit()
                    continue

                q_text = """
                    SELECT id, telegram_chat_id, telegram_first_name, telegram_username FROM conversations
                    WHERE tenant_id = :tid AND source_type = 'dm' AND status != 'closed'
                """
                params: dict = {"tid": tenant_id}
                if target_conv_ids and isinstance(target_conv_ids, list):
                    q_text += " AND id = ANY(:cids)"
                    import uuid as _uuid_mod
                    params["cids"] = [_uuid_mod.UUID(c) if isinstance(c, str) else c for c in target_conv_ids]
                elif filter_type == "ordered":
                    q_text += " AND id IN (SELECT c.id FROM conversations c JOIN leads l ON l.conversation_id = c.id JOIN orders o ON o.lead_id = l.id WHERE c.tenant_id = :tid)"
                q_text += " LIMIT 5000"

                convs = (await db.execute(_sql(q_text), params)).fetchall()

                sent = 0
                failed = 0
                recipients_log = []
                import asyncio as _aio
                import uuid as _uuid_mod2
                for conv_id, chat_id, first_name, username in convs:
                    r_info = {"name": first_name or "—", "username": username, "conversation_id": str(conv_id)}
                    try:
                        if image_url:
                            tg_sent = await client.send_file(chat_id, file=image_url, caption=msg_text, force_document=False)
                        else:
                            tg_sent = await client.send_message(chat_id, msg_text)
                        sent += 1
                        r_info["sent"] = True

                        # Create Message record so it appears in admin conversation detail
                        tg_msg_id = getattr(tg_sent, "id", None)
                        msg_id = _uuid_mod2.uuid4()
                        await db.execute(
                            _sql(
                                "INSERT INTO messages (id, tenant_id, conversation_id, telegram_message_id, direction, sender_type, raw_text, ai_generated, created_at)"
                                " VALUES (:id, :tid, :cid, :tg_mid, 'outbound', 'human_admin', :text, false, now())"
                            ),
                            {"id": msg_id, "tid": tenant_id, "cid": conv_id, "tg_mid": tg_msg_id, "text": msg_text},
                        )
                        await db.execute(
                            _sql("UPDATE conversations SET last_message_at = now() WHERE id = :cid"),
                            {"cid": conv_id},
                        )

                        await _aio.sleep(0.3)
                    except Exception:
                        failed += 1
                        r_info["sent"] = False
                    recipients_log.append(r_info)

                import json as _json
                await db.execute(
                    _sql("UPDATE broadcast_history SET status = 'sent', sent_count = :sent, failed_count = :failed, sent_at = now(), recipients_json = :rj WHERE id = :id"),
                    {"id": bid, "sent": sent, "failed": failed, "rj": _json.dumps(recipients_log, ensure_ascii=False)},
                )
                await db.commit()
                logger.info("Scheduled broadcast %s complete: %d sent, %d failed", bid, sent, failed)
            except Exception:
                logger.exception("Failed to execute scheduled broadcast %s", bid)
                await db.execute(_sql("UPDATE broadcast_history SET status = 'failed' WHERE id = :id"), {"id": bid})
                await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting AI Closer...")

    # Validate secrets — refuse to start with known defaults
    _DANGEROUS_DEFAULTS = {"CHANGE-ME-IN-PRODUCTION", "CHANGE-ME-32-BYTES-KEY-HERE!!!!"}
    if settings.secret_key in _DANGEROUS_DEFAULTS:
        if not settings.debug:
            raise RuntimeError("FATAL: secret_key is set to a known default. Set SECRET_KEY in .env before running in production.")
        logger.warning("⚠️  secret_key is a known default — OK for dev, NEVER use in production!")
    if settings.encryption_key in _DANGEROUS_DEFAULTS:
        if not settings.debug:
            raise RuntimeError("FATAL: encryption_key is set to a known default. Set ENCRYPTION_KEY in .env before running in production.")
        logger.warning("⚠️  encryption_key is a known default — OK for dev, NEVER use in production!")

    try:
        await _run_startup_migrations()
        logger.info("Startup migrations done")
    except Exception:
        logger.exception("Startup migrations failed (non-fatal)")
    try:
        from src.telegram.service import start_all_clients

        await start_all_clients()
        logger.info("Telegram clients started")
    except Exception:
        logger.exception("Failed to start Telegram clients (non-fatal on dev)")

    # Recover any message buffers lost during a previous crash
    try:
        from src.telegram.service import recover_orphaned_buffers

        recovered = await recover_orphaned_buffers()
        if recovered:
            logger.info("Recovered %d orphaned message buffer(s)", recovered)
    except Exception:
        logger.exception("Buffer recovery failed (non-fatal)")

    # Cleanup expired draft orders (>2h old) and unreserve inventory
    try:
        from src.dashboard.router import cleanup_expired_drafts

        cancelled = await cleanup_expired_drafts(max_age_hours=2)
        if cancelled:
            logger.info("Cleaned up %d expired draft order(s) on startup", cancelled)
    except Exception:
        logger.exception("Draft cleanup failed (non-fatal)")

    # Start scheduled broadcast checker
    import asyncio

    async def _check_scheduled_broadcasts():
        """Check for due scheduled broadcasts every 30 seconds."""
        while True:
            try:
                await asyncio.sleep(30)
                await _execute_due_broadcasts()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduled broadcast checker error")

    scheduler_task = asyncio.create_task(_check_scheduled_broadcasts())

    yield

    # Shutdown
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down AI Closer...")
    try:
        from src.telegram.service import telegram_manager

        await telegram_manager.stop_all()
    except Exception:
        logger.exception("Error during shutdown")


app = FastAPI(
    title="AI Closer",
    description="AI Sales Closer for Telegram Stores",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from src.core.rate_limit import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router)
app.include_router(tenants_router)
app.include_router(telegram_router)
app.include_router(catalog_router)
app.include_router(conversations_router)
app.include_router(leads_router)
app.include_router(orders_router)
app.include_router(handoffs_router)
app.include_router(dashboard_router)
app.include_router(import_router)
app.include_router(ai_router)
app.include_router(training_router)
app.include_router(analytics_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
