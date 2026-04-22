"""SSE endpoint — streams real-time events to authenticated clients.

Uses short-lived SSE tokens (5 min) instead of full JWTs in URL query parameters.
Clients first obtain an SSE token via POST /events/token (requires Bearer JWT),
then connect to /events/stream with the short-lived token.
"""

import asyncio
import json
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from src.auth.deps import get_current_user
from src.auth.models import User
from src.core.security import create_sse_token, verify_sse_token
from src.sse.event_bus import subscribe

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sse"])

# Keepalive interval (seconds) — prevents proxy/browser timeout
_KEEPALIVE_INTERVAL = 15
# SSE token TTL — after this the client must obtain a new token and reconnect
_SSE_TOKEN_TTL = 300  # 5 minutes
# Max concurrent SSE connections per worker — prevents Redis connection exhaustion
_MAX_SSE_CONNECTIONS = 200
_active_connections = 0


@router.post("/events/token")
async def get_sse_token(user: User = Depends(get_current_user)):
    """Exchange a Bearer JWT for a short-lived SSE token (5 min).

    The SSE token is safe to pass in URL query params — it's short-lived,
    scoped to SSE only, and doesn't expose the session JWT.
    """
    token = create_sse_token(str(user.id), str(user.tenant_id), ttl_seconds=_SSE_TOKEN_TTL)
    return {"token": token, "expires_in": _SSE_TOKEN_TTL}


@router.get("/events/stream")
async def event_stream(
    token: str = Query(..., description="Short-lived SSE token from POST /events/token"),
    conversation_id: UUID | None = Query(None, description="Subscribe to specific conversation"),
):
    """SSE endpoint. Returns text/event-stream with real-time events."""
    # --- Connection limit ---
    if _active_connections >= _MAX_SSE_CONNECTIONS:
        raise HTTPException(status_code=503, detail="Too many SSE connections")

    # --- Auth: validate short-lived SSE token ---
    payload = verify_sse_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired SSE token")

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
    - Periodically re-validates SSE token (catches expiry)
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

            # Periodic token re-validation (every 60s — token is only 5 min)
            if now - last_token_check >= 60:
                last_token_check = now
                payload = verify_sse_token(token)
                if not payload:
                    yield 'event: auth_expired\ndata: {"reason": "sse_token_expired"}\n\n'
                    return

    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("SSE connection error", exc_info=True)
    finally:
        _active_connections -= 1
