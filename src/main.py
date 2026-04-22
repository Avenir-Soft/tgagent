"""AI Closer — main FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.core.logging_config import setup_logging
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
from src.platform.router import router as platform_router
from src.sse.router import router as sse_router

setup_logging()
logger = logging.getLogger(__name__)


async def _run_alembic_upgrade():
    """Run Alembic migrations on startup. All schema DDL is managed by Alembic."""
    import os
    import subprocess
    cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True, text=True, timeout=30,
        cwd=cwd,
    )
    if result.returncode != 0:
        logger.warning("Alembic upgrade failed: %s", result.stderr[:500])


async def _execute_due_broadcasts():
    """Find and execute any scheduled broadcasts that are due."""
    from sqlalchemy import text as _sql
    from src.core.database import async_session_factory

    async with async_session_factory() as db:
        # Atomically claim due broadcasts to prevent double-send on multiple instances
        result = await db.execute(
            _sql(
                "UPDATE broadcast_history SET status = 'sending'"
                " WHERE id IN ("
                "   SELECT id FROM broadcast_history"
                "   WHERE status = 'scheduled' AND scheduled_at <= now()"
                "   FOR UPDATE SKIP LOCKED"
                " ) RETURNING id, tenant_id, message_text, image_url, filter_type, created_by_user_id, target_conversation_ids"
            )
        )
        due = result.fetchall()
        if not due:
            return
        await db.commit()

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
                        # Resolve entity — after restart Telethon may not have the peer cached
                        try:
                            entity = await client.get_input_entity(chat_id)
                        except ValueError:
                            if username:
                                entity = await client.get_input_entity(username)
                            else:
                                raise
                        if image_url:
                            tg_sent = await client.send_file(entity, file=image_url, caption=msg_text, force_document=False)
                        else:
                            tg_sent = await client.send_message(entity, msg_text)
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
                    except Exception as e:
                        logger.warning("Broadcast send failed for conversation %s: %s", conv_id, e)
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
        await _run_alembic_upgrade()
        logger.info("Alembic migrations done")
    except Exception:
        logger.exception("Alembic migrations failed (non-fatal)")
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
        from src.dashboard.service import cleanup_expired_drafts

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
        from src.core.redis import close_redis
        await close_redis()
    except Exception:
        logger.exception("Error closing shared Redis pool")
    try:
        from src.sse.event_bus import close_event_bus
        await close_event_bus()
    except Exception:
        logger.exception("Error closing SSE event bus")
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

# Security headers + request context (raw ASGI middleware — does NOT buffer response body, safe for SSE)
from src.core.logging_config import generate_request_id, set_log_context

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


class _SecurityHeadersMiddleware:
    """Raw ASGI middleware that injects security headers and request ID without buffering the response body."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract or generate request_id from incoming headers
        rid = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                rid = value.decode("latin-1")
                break
        if not rid:
            rid = generate_request_id()
        set_log_context(request_id=rid)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode("latin-1")))
                headers.extend(_SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            set_log_context(request_id=None, tenant_id=None, conversation_id=None)

app.add_middleware(_SecurityHeadersMiddleware)

# CORS
# NOTE: In production, cors_origins should be restricted to the actual frontend domain(s).
# The current list includes localhost/LAN IPs for development convenience.
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Static files (avatars etc.)
import os as _os
from fastapi.staticfiles import StaticFiles
_static_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "static")
_os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

_uploads_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "uploads")
_os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")

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
app.include_router(platform_router)
app.include_router(sse_router)


@app.get("/health")
async def health():
    """Liveness probe — always returns 200 if the process is alive."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe — checks DB, Redis, and Telegram connectivity."""
    from src.core.database import engine
    from src.core.security import _redis
    from src.telegram.service import telegram_manager

    checks: dict[str, str] = {}

    # Database
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis
    try:
        await _redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Telegram clients
    try:
        clients = telegram_manager._clients
        connected = sum(1 for c in clients.values() if c.is_connected())
        checks["telegram"] = f"ok: {connected}/{len(clients)} connected"
    except Exception as e:
        checks["telegram"] = f"error: {e}"

    # Circuit breakers
    from src.core.circuit_breaker import openai_breaker
    checks["openai_circuit_breaker"] = openai_breaker.state.value

    all_ok = all(v.startswith("ok") or v == "closed" for v in checks.values())
    status_code = 200 if all_ok else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )
