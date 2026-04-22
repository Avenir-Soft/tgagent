"""Shared Redis connection pool — single instance for the entire application.

All modules that need Redis should import `get_redis()` from here instead of
creating their own `aioredis.from_url()` connections. This avoids 4+ duplicate
connection pools consuming file descriptors and memory.

Exception: SSE pub/sub (src/sse/event_bus.py) intentionally creates per-subscriber
connections because Redis pub/sub requires dedicated connections per listener.
"""

import redis.asyncio as aioredis

from src.core.config import settings

# Shared connection pool — created once at module import
redis_pool: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    retry_on_timeout=True,
    socket_connect_timeout=5,
    socket_timeout=5,
    health_check_interval=30,
    max_connections=20,
)


def get_redis() -> aioredis.Redis:
    """Return the shared Redis connection pool instance.

    This is synchronous — returns immediately. The actual network I/O
    happens when you await a command on the returned client.
    """
    return redis_pool


async def close_redis() -> None:
    """Close the shared Redis pool. Call on application shutdown."""
    await redis_pool.aclose()
