"""Rate limiting configuration — per-IP (slowapi) + per-tenant (Redis)."""

import logging
import time

from fastapi import HTTPException, status
from starlette.requests import Request

from slowapi import Limiter

logger = logging.getLogger(__name__)

# ── Per-IP limiter (slowapi — applied per-endpoint) ─────────────────────────


def _get_real_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For (reverse proxy) or fall back to direct IP."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First IP in the chain is the original client
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


limiter = Limiter(key_func=_get_real_ip)


# ── Per-tenant limiter (Redis fixed-window counter) ─────────────────────────

# Default: 200 requests per minute per tenant
TENANT_RATE_LIMIT = 200
TENANT_RATE_WINDOW = 60  # seconds


async def check_tenant_rate_limit(tenant_id: str) -> None:
    """Check per-tenant rate limit using Redis INCR (fixed-window counter).

    Called from get_current_user after authentication succeeds.
    Fail-open: if Redis is unavailable, requests are allowed through.
    """
    try:
        from src.core.security import _redis

        window = int(time.time()) // TENANT_RATE_WINDOW
        key = f"tenant_rl:{tenant_id}:{window}"

        count = await _redis.incr(key)
        if count == 1:
            await _redis.expire(key, TENANT_RATE_WINDOW + 5)

        if count > TENANT_RATE_LIMIT:
            logger.warning(
                "Tenant %s rate limited: %d/%d req/min",
                tenant_id, count, TENANT_RATE_LIMIT,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Tenant rate limit exceeded ({TENANT_RATE_LIMIT} req/{TENANT_RATE_WINDOW}s)",
                headers={"Retry-After": str(TENANT_RATE_WINDOW)},
            )
    except HTTPException:
        raise
    except Exception:
        # Fail-open: if Redis is down, don't block requests
        logger.debug("Tenant rate limit check failed (fail-open)", exc_info=True)
