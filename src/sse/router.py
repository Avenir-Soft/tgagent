"""SSE endpoint — streams real-time events to authenticated clients.

EventSource cannot set custom headers, so JWT is passed as a query parameter.
Each client subscribes to their tenant channel + optionally a conversation channel.
"""

import asyncio
import logging
import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from src.core.security import decode_access_token, is_token_blacklisted
from src.sse.event_bus import subscribe

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sse"])

# Keepalive interval (seconds) — prevents proxy/browser timeout
_KEEPALIVE_INTERVAL = 15
# Re-validate JWT every N seconds to catch logout/expiry
_TOKEN_CHECK_INTERVAL = 300


@router.get("/events/stream")
async def event_stream(
    token: str = Query(..., description="JWT access token"),
    conversation_id: UUID | None = Query(None, description="Subscribe to specific conversation"),
):
    """SSE endpoint. Returns text/event-stream with real-time events."""
    # --- Auth: manual JWT validation (can't use Depends with SSE) ---
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    if await is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token revoked")

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id in token")

    # Build channel list
    channels = [f"sse:{tenant_id}:tenant"]
    if conversation_id:
        channels.append(f"sse:{tenant_id}:conversation:{conversation_id}")

    return StreamingResponse(
        _event_generator(channels, token),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_generator(channels: list[str], token: str):
    """Async generator that yields SSE-formatted lines.

    - Listens to Redis pub/sub channels
    - Sends keepalive comments every 15s
    - Periodically re-validates JWT
    """
    import redis.asyncio as aioredis
    from src.core.config import settings
    import json

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()

    try:
        await pubsub.subscribe(*channels)
        last_keepalive = time.monotonic()
        last_token_check = time.monotonic()

        while True:
            # Check for messages (non-blocking with 1s timeout)
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0,
            )

            if msg and msg["type"] == "message":
                # Parse to extract event type for SSE "event:" field
                try:
                    data = json.loads(msg["data"])
                    event_type = data.get("event", "message")
                    yield f"event: {event_type}\ndata: {msg['data']}\n\n"
                except (json.JSONDecodeError, TypeError):
                    yield f"data: {msg['data']}\n\n"
                last_keepalive = time.monotonic()

            # Keepalive: prevent connection timeout
            now = time.monotonic()
            if now - last_keepalive >= _KEEPALIVE_INTERVAL:
                yield ": keepalive\n\n"
                last_keepalive = now

            # Periodic token re-validation
            if now - last_token_check >= _TOKEN_CHECK_INTERVAL:
                last_token_check = now
                payload = decode_access_token(token)
                if not payload:
                    yield 'event: auth_expired\ndata: {"reason": "token_expired"}\n\n'
                    break
                if await is_token_blacklisted(token):
                    yield 'event: auth_expired\ndata: {"reason": "token_revoked"}\n\n'
                    break

    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("SSE connection error", exc_info=True)
    finally:
        try:
            await pubsub.unsubscribe(*channels)
            await pubsub.aclose()
            await r.aclose()
        except Exception:
            pass
