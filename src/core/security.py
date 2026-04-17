from datetime import datetime, timedelta, timezone

import bcrypt
import redis.asyncio as aioredis
from jose import JWTError, jwt

from src.core.config import settings

_redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    retry_on_timeout=True,
    socket_connect_timeout=5,
    socket_timeout=5,
    health_check_interval=30,
)


async def blacklist_token(token: str) -> None:
    """Add a JWT token to the blacklist in Redis."""
    payload = decode_access_token(token)
    if payload and "exp" in payload:
        ttl = int(payload["exp"] - datetime.now(timezone.utc).timestamp())
        if ttl > 0:
            await _redis.setex(f"bl:{token}", ttl, "1")
            return
    await _redis.setex(f"bl:{token}", settings.access_token_expire_minutes * 60, "1")


async def is_token_blacklisted(token: str) -> bool:
    return await _redis.exists(f"bl:{token}") > 0


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


async def create_refresh_token(user_id: str, tenant_id: str) -> str:
    """Create an opaque refresh token stored in Redis."""
    import secrets
    token = secrets.token_urlsafe(48)
    ttl = settings.refresh_token_expire_days * 86400
    data = f"{user_id}:{tenant_id}"
    await _redis.setex(f"rt:{token}", ttl, data)
    return token


async def validate_refresh_token(token: str) -> tuple[str, str] | None:
    """Validate and consume a refresh token (one-time use). Returns (user_id, tenant_id) or None."""
    data = await _redis.get(f"rt:{token}")
    if not data:
        return None
    # Delete immediately — one-time use (rotation)
    await _redis.delete(f"rt:{token}")
    parts = data.split(":", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


async def revoke_refresh_token(token: str) -> None:
    """Explicitly revoke a refresh token."""
    await _redis.delete(f"rt:{token}")


def create_media_token(user_id: str, ttl_seconds: int = 300) -> str:
    """Create a short-lived HMAC-signed token for media access (no JWT in URL)."""
    import hmac
    import hashlib
    import time

    expires = int(time.time()) + ttl_seconds
    payload = f"{user_id}.{expires}"
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"
