"""SSE event bus — Redis pub/sub for real-time event delivery.

Channels:
  sse:{tenant_id}:conversation:{conversation_id}  — per-conversation events
  sse:{tenant_id}:tenant                            — tenant-wide events
"""

import json
import logging
from typing import AsyncGenerator

import redis.asyncio as aioredis

from src.core.config import settings

logger = logging.getLogger(__name__)

# Dedicated publisher connection (module-level, lazy init)
_redis_pub: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis_pub
    if _redis_pub is None:
        _redis_pub = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_pub


async def publish_event(channel: str, event: dict) -> None:
    """Publish an event to a Redis channel. Fire-and-forget — never raises."""
    try:
        r = await _get_redis()
        await r.publish(channel, json.dumps(event, default=str))
    except Exception:
        logger.warning("Failed to publish SSE event to %s", channel, exc_info=True)


async def subscribe(channels: list[str]) -> AsyncGenerator[dict, None]:
    """Subscribe to Redis channels and yield parsed event dicts.

    Creates its own connection so each SSE client has independent pubsub.
    Caller must handle CancelledError for cleanup.
    """
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(*channels)
        while True:
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0,
            )
            if msg and msg["type"] == "message":
                try:
                    yield json.loads(msg["data"])
                except (json.JSONDecodeError, TypeError):
                    pass
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()
        await r.aclose()


async def close_event_bus() -> None:
    """Close the publisher connection. Called on app shutdown."""
    global _redis_pub
    if _redis_pub:
        await _redis_pub.aclose()
        _redis_pub = None
