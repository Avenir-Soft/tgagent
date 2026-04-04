import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import text
from src.core.config import settings

async def check():
    eng = create_async_engine(settings.database_url)
    async with AsyncSession(eng) as db:
        # Check aliases matching speaker-related terms
        rows = await db.execute(text(
            "SELECT pa.alias_text, p.name FROM product_aliases pa "
            "JOIN products p ON p.id = pa.product_id "
            "WHERE pa.alias_text ILIKE '%колонк%' OR pa.alias_text ILIKE '%speaker%' "
            "OR pa.alias_text ILIKE '%динамик%' OR pa.alias_text ILIKE '%аудио%' "
            "OR pa.alias_text ILIKE '%наушник%' OR pa.alias_text ILIKE '%airpods%' "
            "ORDER BY p.name, pa.alias_text"
        ))
        print("=== Aliases matching колонка/speaker/audio ===")
        for r in rows:
            print(f"  {r[1]}: \"{r[0]}\"")

        # Check category names
        print("\n=== Categories ===")
        cats = await db.execute(text("SELECT name FROM categories WHERE is_active = true ORDER BY name"))
        for r in cats:
            print(f"  {r[0]}")

        # Check JBL aliases
        print("\n=== JBL aliases ===")
        jbl = await db.execute(text(
            "SELECT pa.alias_text FROM product_aliases pa "
            "JOIN products p ON p.id = pa.product_id "
            "WHERE p.name ILIKE '%JBL%' ORDER BY pa.alias_text"
        ))
        for r in jbl:
            print(f"  \"{r[0]}\"")

        # Check AirPods aliases
        print("\n=== AirPods aliases ===")
        air = await db.execute(text(
            "SELECT pa.alias_text FROM product_aliases pa "
            "JOIN products p ON p.id = pa.product_id "
            "WHERE p.name ILIKE '%AirPods%' ORDER BY pa.alias_text"
        ))
        for r in air:
            print(f"  \"{r[0]}\"")

        # Check Sony WH aliases
        print("\n=== Sony WH aliases ===")
        sony = await db.execute(text(
            "SELECT pa.alias_text FROM product_aliases pa "
            "JOIN products p ON p.id = pa.product_id "
            "WHERE p.name ILIKE '%WH-1000%' ORDER BY pa.alias_text"
        ))
        for r in sony:
            print(f"  \"{r[0]}\"")
    await eng.dispose()

asyncio.run(check())
