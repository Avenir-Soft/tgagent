"""SSE endpoint — streams real-time events to authenticated clients.

EventSource cannot set custom headers, so JWT is passed as a query parameter.
Each client subscribes to their tenant channel + optionally a conversation channel.
"""

import asyncio
import json
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
# Max concurrent SSE connections per worker — prevents Redis connection exhaustion
_MAX_SSE_CONNECTIONS = 200
_active_connections = 0


@router.get("/events/stream")
async def event_stream(
    token: str = Query(..., description="JWT access token"),
    conversation_id: UUID | None = Query(None, description="Subscribe to specific conversation"),
):
    """SSE endpoint. Returns text/event-stream with real-time events."""
    # --- Connection limit ---
    if _active_connections >= _MAX_SSE_CONNECTIONS:
        raise HTTPException(status_code=503, detail="Too many SSE connections")

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

    - Uses event_bus.subscribe() for Redis pub/sub (no duplicated connection logic)
    - Sends keepalive comments every 15s
    - Periodically re-validates JWT
    - Tracks active connections for capacity limiting
    """
    global _active_connections
    _active_connections += 1

    try:
        # Tell browser to wait 10s before reconnecting (default ~3s is too aggressive)
        yield "retry: 10000\n\n"

        last_keepalive = time.monotonic()
        last_token_check = time.monotonic()

        async for event in subscribe(channels):
            now = time.monotonic()

            if event is not None:
                event_type = event.get("event", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, default=str)}\n\n"
                last_keepalive = now

            # Keepalive: prevent connection timeout
            if now - last_keepalive >= _KEEPALIVE_INTERVAL:
                yield ": keepalive\n\n"
                last_keepalive = now

            # Periodic token re-validation
            if now - last_token_check >= _TOKEN_CHECK_INTERVAL:
                last_token_check = now
                payload = decode_access_token(token)
                if not payload:
                    yield 'event: auth_expired\ndata: {"reason": "token_expired"}\n\n'
                    return
                if await is_token_blacklisted(token):
                    yield 'event: auth_expired\ndata: {"reason": "token_revoked"}\n\n'
                    return

    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("SSE connection error", exc_info=True)
    finally:
        _active_connections -= 1
