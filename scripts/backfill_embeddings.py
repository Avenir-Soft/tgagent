"""Backfill embeddings for all existing products that don't have one.

Usage:
    cd "tg agent"
    .venv/bin/python scripts/backfill_embeddings.py
"""
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.database import async_session_factory
# Import all models to register with SQLAlchemy
from src.tenants.models import *  # noqa
from src.auth.models import *  # noqa
from src.telegram.models import *  # noqa
from src.catalog.models import *  # noqa
from src.conversations.models import *  # noqa
from src.leads.models import *  # noqa
from src.orders.models import *  # noqa
from src.handoffs.models import *  # noqa
from src.ai.models import *  # noqa
from src.catalog.models import Product
from src.core.vector import generate_embedding, build_embedding_text


async def backfill():
    async with async_session_factory() as db:
        result = await db.execute(
            select(Product)
            .where(Product.embedding.is_(None), Product.is_active.is_(True))
            .options(selectinload(Product.category), selectinload(Product.aliases))
        )
        products = result.scalars().all()
        total = len(products)
        print(f"Backfilling {total} products...")

        success = 0
        failed = 0
        for i, product in enumerate(products):
            text = build_embedding_text(product)
            embedding = await generate_embedding(text)
            if embedding:
                product.embedding = embedding
                success += 1
                print(f"  [{i + 1}/{total}] {product.name} -- OK")
            else:
                failed += 1
                print(f"  [{i + 1}/{total}] {product.name} -- FAILED")

            # Commit in batches of 10
            if (i + 1) % 10 == 0:
                await db.commit()

        await db.commit()
        print(f"\nDone! {success} succeeded, {failed} failed out of {total} products.")


if __name__ == "__main__":
    asyncio.run(backfill())
