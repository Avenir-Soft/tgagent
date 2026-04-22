"""Vector search utilities using pgvector + OpenAI embeddings.

Provides embedding generation and text construction for hybrid product search.
Used alongside ILIKE for best-of-both-worlds matching (semantic + exact).
"""

import hashlib
import json
import logging

from openai import AsyncOpenAI

from src.core.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536  # text-embedding-3-small output dimension


async def generate_embedding(text: str) -> list[float] | None:
    """Generate embedding vector for text using OpenAI API.

    Returns None on failure (non-fatal) so callers can fall back to ILIKE-only.
    """
    if not text or not text.strip():
        return None
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.embeddings.create(
            input=text.strip()[:8000],  # API limit ~8k tokens
            model=settings.openai_embedding_model or "text-embedding-3-small",
        )
        return response.data[0].embedding
    except Exception as e:
        logger.warning("Embedding generation failed: %s", e)
        return None


async def generate_embedding_cached(text: str) -> list[float] | None:
    """Generate embedding with Redis cache (5 min TTL)."""
    cache_key = f"embed:{hashlib.md5(text.strip().lower().encode()).hexdigest()}"
    try:
        from src.core.redis import get_redis
        r = get_redis()
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    embedding = await generate_embedding(text)
    if embedding:
        try:
            from src.core.redis import get_redis
            r = get_redis()
            await r.setex(cache_key, 300, json.dumps(embedding))
        except Exception:
            pass
    return embedding


def build_embedding_text(product) -> str:
    """Build text for product embedding from all available fields.

    Concatenates name, brand, model, category, description (truncated),
    and all aliases into a single string for embedding.
    """
    parts = [product.name or ""]
    if product.brand:
        parts.append(product.brand)
    if product.model:
        parts.append(product.model)
    if hasattr(product, "category") and product.category:
        parts.append(product.category.name)
    if product.description:
        parts.append(product.description[:500])
    # Add aliases if loaded
    if hasattr(product, "aliases") and product.aliases:
        for alias in product.aliases:
            parts.append(alias.alias_text)
    return " ".join(parts).strip()
