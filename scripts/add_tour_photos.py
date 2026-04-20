"""Add photos to Easy Tour tours from free image sources."""

import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select, text as sql_text
from src.core.database import async_session_factory
from src.catalog.models import Product, ProductMedia
from src.tenants.models import *  # noqa
from src.auth.models import *  # noqa
from src.telegram.models import *  # noqa
from src.conversations.models import *  # noqa
from src.leads.models import *  # noqa
from src.orders.models import *  # noqa
from src.handoffs.models import *  # noqa

# Tour name → photo URLs (Unsplash free images, resized)
TOUR_PHOTOS = {
    "Paltau sharshara": [
        "https://images.unsplash.com/photo-1432405972618-c6b0cfba8673?w=800&q=80",  # waterfall
        "https://images.unsplash.com/photo-1546587348-d12660c30c50?w=800&q=80",  # mountain stream
    ],
    "Chukuraksu sharshara": [
        "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=800&q=80",  # waterfall in forest
        "https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?w=800&q=80",  # green nature
    ],
    "Ispay sharshara": [
        "https://images.unsplash.com/photo-1509316975850-ff9c5deb0cd9?w=800&q=80",  # tall waterfall
        "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=800&q=80",  # forest trail
    ],
    "Chimgan tog' yurish": [
        "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=800&q=80",  # mountains
        "https://images.unsplash.com/photo-1551632811-561732d1e306?w=800&q=80",  # hiking trail
    ],
    "Oqtosh tog' yurish": [
        "https://images.unsplash.com/photo-1486870591958-9b9d0d1dda99?w=800&q=80",  # mountain peak
        "https://images.unsplash.com/photo-1501555088652-021faa106b9b?w=800&q=80",  # hiking adventure
    ],
    "Bungee jumping": [
        "https://images.unsplash.com/photo-1541185933-ef5d8ed016c2?w=800&q=80",  # bungee jump
        "https://images.unsplash.com/photo-1504280390367-361c6d9f38f4?w=800&q=80",  # adventure bridge
    ],
    "Zipline + Kayak": [
        "https://images.unsplash.com/photo-1530866495561-507c83b0e290?w=800&q=80",  # zipline
        "https://images.unsplash.com/photo-1472745942893-4b9f730c7668?w=800&q=80",  # kayaking
    ],
    "Nefrit ko'l 4x4": [
        "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?w=800&q=80",  # road trip
        "https://images.unsplash.com/photo-1439066615861-d1af74d74000?w=800&q=80",  # mountain lake
    ],
    "Tuzkon kemping": [
        "https://images.unsplash.com/photo-1504851149312-7a075b496cc7?w=800&q=80",  # camping night
        "https://images.unsplash.com/photo-1487730116645-74489c95b41b?w=800&q=80",  # campfire
    ],
    "Xiva sayohat": [
        "https://images.unsplash.com/photo-1565008576549-57569a49371d?w=800&q=80",  # Uzbekistan architecture
        "https://images.unsplash.com/photo-1596484552834-6a58f850e0a1?w=800&q=80",  # Central Asia mosque
    ],
    "Mewa Party": [
        "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=800&q=80",  # food festival
        "https://images.unsplash.com/photo-1488459716781-31db52582fe9?w=800&q=80",  # fruits
    ],
    "Qirg'iziston sayohat": [
        "https://images.unsplash.com/photo-1530866495561-507c83b0e290?w=800&q=80",  # Kyrgyzstan mountains
        "https://images.unsplash.com/photo-1527004013197-933c4bb611b3?w=800&q=80",  # mountain scenery
    ],
}


async def add_photos():
    async with async_session_factory() as db:
        # Get Easy Tour tenant
        result = await db.execute(sql_text("SELECT id FROM tenants WHERE slug = 'easy-tour'"))
        row = result.first()
        if not row:
            print("Easy Tour tenant not found!")
            return
        tid = row[0]

        # Clean existing media for this tenant
        await db.execute(sql_text("DELETE FROM product_media WHERE tenant_id = :tid"), {"tid": str(tid)})
        await db.flush()

        # Get products
        products = await db.execute(
            select(Product).where(Product.tenant_id == tid)
        )
        product_map = {p.name: p for p in products.scalars().all()}

        total = 0
        for tour_name, urls in TOUR_PHOTOS.items():
            product = product_map.get(tour_name)
            if not product:
                print(f"  SKIP: {tour_name} (not found)")
                continue

            for i, url in enumerate(urls):
                media = ProductMedia(
                    tenant_id=tid,
                    product_id=product.id,
                    url=url,
                    media_type="photo",
                    sort_order=i,
                )
                db.add(media)
                total += 1

            print(f"  + {tour_name}: {len(urls)} photos")

        await db.commit()
        print(f"\nDone! Added {total} photos to {len(TOUR_PHOTOS)} tours.")


if __name__ == "__main__":
    asyncio.run(add_photos())
