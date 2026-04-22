import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from src.core.config import settings
from src.core.redis import get_redis

_logger = logging.getLogger(__name__)

_redis = get_redis()


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


def create_sse_token(user_id: str, tenant_id: str, ttl_seconds: int = 300) -> str:
    """Create a short-lived JWT token for SSE connections (5 min default).

    Avoids exposing the full session JWT in URL query parameters which
    appear in server logs, browser history, and proxy logs.
    """
    expire = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "purpose": "sse",
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def verify_sse_token(token: str) -> dict | None:
    """Verify a short-lived SSE token. Returns payload dict or None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("purpose") != "sse":
            return None
        return payload
    except JWTError:
        return None


# ── Fernet symmetric encryption for API keys ────────────────────────────────

def _get_fernet() -> Fernet:
    """Derive a URL-safe base64 Fernet key from the ENCRYPTION_KEY setting.

    Fernet requires exactly 32 bytes, base64-encoded.  We SHA-256 the raw
    setting value to guarantee the right length, then base64-encode.
    """
    import base64
    import hashlib

    raw = settings.encryption_key.encode("utf-8")
    key_bytes = hashlib.sha256(raw).digest()          # always 32 bytes
    fernet_key = base64.urlsafe_b64encode(key_bytes)  # 44 chars, Fernet-compatible
    return Fernet(fernet_key)


def encrypt_api_key(plain_key: str) -> str:
    """Encrypt an API key string using Fernet. Returns base64 ciphertext."""
    f = _get_fernet()
    return f.encrypt(plain_key.encode("utf-8")).decode("utf-8")


def decrypt_api_key(encrypted: str) -> str:
    """Decrypt an API key previously encrypted with encrypt_api_key.

    Returns the plaintext key, or raises ValueError on failure.
    """
    try:
        f = _get_fernet()
        return f.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as exc:
        _logger.error("Failed to decrypt API key: %s", type(exc).__name__)
        raise ValueError("Failed to decrypt API key — encryption key may have changed") from exc
