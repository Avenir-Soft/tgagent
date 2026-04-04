from datetime import datetime, timedelta, timezone

import bcrypt
import redis
from jose import JWTError, jwt

from src.core.config import settings

_redis = redis.from_url(settings.redis_url, decode_responses=True)


def blacklist_token(token: str) -> None:
    """Add a JWT token to the blacklist in Redis."""
    payload = decode_access_token(token)
    if payload and "exp" in payload:
        ttl = int(payload["exp"] - datetime.now(timezone.utc).timestamp())
        if ttl > 0:
            _redis.setex(f"bl:{token}", ttl, "1")
            return
    _redis.setex(f"bl:{token}", settings.access_token_expire_minutes * 60, "1")


def is_token_blacklisted(token: str) -> bool:
    return _redis.exists(f"bl:{token}") > 0


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
