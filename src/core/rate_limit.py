"""Rate limiting configuration — shared limiter instance."""

from starlette.requests import Request

from slowapi import Limiter


def _get_real_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For (reverse proxy) or fall back to direct IP."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First IP in the chain is the original client
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


limiter = Limiter(key_func=_get_real_ip)
