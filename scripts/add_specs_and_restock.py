"""Add product specifications and restock out-of-stock products."""

import asyncio
import sys

sys.path.insert(0, ".")

# Import ALL models so SQLAlchemy metadata is complete
from src.tenants.models import *  # noqa
from src.auth.models import *  # noqa
from src.telegram.models import *  # noqa
from src.catalog.models import *  # noqa
from src.conversations.models import *  # noqa
from src.leads.models import *  # noqa
from src.orders.models import *  # noqa
from src.handoffs.models import *  # noqa
from src.ai.models import *  # noqa
from src.core.audit import *  # noqa

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from src.core.database import async_session_factory
from src.catalog.models import ProductVariant, Inventory


# Product specs by variant title prefix
SPECS = {
    # iPhones
    "iPhone 15 128GB": {
        "processor": "Apple A16 Bionic",
        "display": "6.1\" Super Retina XDR OLED",
        "camera": "48MP + 12MP",
        "battery": "3349 mAh",
        "ram_spec": "6GB",
    },
    "iPhone 15 Pro 256GB": {
        "processor": "Apple A17 Pro",
        "display": "6.1\" Super Retina XDR ProMotion OLED, 120Hz",
        "camera": "48MP + 12MP + 12MP",
        "battery": "3274 mAh",
        "ram_spec": "8GB",
    },
    "iPhone 15 Pro Max 256GB": {
        "processor": "Apple A17 Pro",
        "display": "6.7\" Super Retina XDR ProMotion OLED, 120Hz",
        "camera": "48MP + 12MP + 12MP + Periscope 5x",
        "battery": "4422 mAh",
        "ram_spec": "8GB",
    },
    # Samsung Galaxy
    "Samsung Galaxy S24 256GB": {
        "processor": "Qualcomm Snapdragon 8 Gen 3 / Exynos 2400",
        "display": "6.2\" Dynamic AMOLED 2X, 120Hz",
        "camera": "50MP + 12MP + 10MP",
        "battery": "4000 mAh",
        "ram_spec": "8GB",
    },
    "Samsung Galaxy S24 Ultra 256GB": {
        "processor": "Qualcomm Snapdragon 8 Gen 3",
        "display": "6.8\" Dynamic AMOLED 2X, 120Hz",
        "camera": "200MP + 12MP + 50MP + 10MP",
        "battery": "5000 mAh",
        "ram_spec": "12GB",
    },
    # Xiaomi
    "Redmi Note 13 Pro 256GB": {
        "processor": "MediaTek Helio G99 Ultra",
        "display": "6.67\" AMOLED, 120Hz",
        "camera": "200MP + 8MP + 2MP",
        "battery": "5100 mAh",
        "ram_spec": "8GB",
    },
    # MacBooks
    "MacBook Air M2 13.6 8/256": {
        "processor": "Apple M2 (8-core CPU, 8-core GPU)",
        "display": "13.6\" Liquid Retina, 2560x1664",
        "battery": "до 18 часов",
        "ram_spec": "8GB",
        "ssd": "256GB SSD",
    },
    "MacBook Air M2 13.6 8/512": {
        "processor": "Apple M2 (8-core CPU, 10-core GPU)",
        "display": "13.6\" Liquid Retina, 2560x1664",
        "battery": "до 18 часов",
        "ram_spec": "8GB",
        "ssd": "512GB SSD",
    },
    "MacBook Pro 14 M3 8/512": {
        "processor": "Apple M3 (8-core CPU, 10-core GPU)",
        "display": "14.2\" Liquid Retina XDR, ProMotion 120Hz",
        "battery": "до 22 часов",
        "ram_spec": "8GB",
        "ssd": "512GB SSD",
    },
    # Laptops
    "ASUS Zenbook 14 OLED 16/512": {
        "processor": "Intel Core Ultra 7 155H",
        "display": "14\" OLED, 2880x1800, 120Hz",
        "battery": "до 13 часов",
        "ram_spec": "16GB LPDDR5X",
        "ssd": "512GB NVMe SSD",
    },
    "Lenovo Legion 5 16 16/512": {
        "processor": "AMD Ryzen 7 7840HS",
        "display": "16\" IPS, 2560x1600, 165Hz",
        "gpu": "NVIDIA RTX 4060 8GB",
        "battery": "до 6 часов",
        "ram_spec": "16GB DDR5",
        "ssd": "512GB NVMe SSD",
    },
    # iPads
    "iPad Air 11 M2 128GB": {
        "processor": "Apple M2",
        "display": "11\" Liquid Retina, 2360x1640",
        "camera": "12MP",
        "battery": "до 10 часов",
        "ram_spec": "8GB",
    },
    "iPad Air 11 M2 256GB": {
        "processor": "Apple M2",
        "display": "11\" Liquid Retina, 2360x1640",
        "camera": "12MP",
        "battery": "до 10 часов",
        "ram_spec": "8GB",
    },
    # Samsung Tab
    "Galaxy Tab S9 128GB": {
        "processor": "Qualcomm Snapdragon 8 Gen 2",
        "display": "11\" Dynamic AMOLED 2X, 120Hz",
        "camera": "13MP",
        "battery": "8400 mAh",
        "ram_spec": "8GB",
    },
    # PlayStation
    "PlayStation 5 Slim 1TB": {
        "processor": "AMD Zen 2 (8 ядер, 3.5GHz)",
        "gpu": "AMD RDNA 2 (10.28 TFLOPS)",
        "storage_spec": "1TB SSD",
        "resolution": "до 4K 120fps / 8K",
    },
    # Xbox
    "Xbox Series X 1TB": {
        "processor": "AMD Zen 2 (8 ядер, 3.8GHz)",
        "gpu": "AMD RDNA 2 (12 TFLOPS)",
        "storage_spec": "1TB NVMe SSD",
        "resolution": "до 4K 120fps / 8K",
    },
    # TVs
    "LG 55\" OLED C3": {
        "display": "55\" 4K OLED evo",
        "refresh_rate": "120Hz",
        "hdr": "Dolby Vision, HDR10, HLG",
        "processor": "α9 Gen6 AI Processor 4K",
        "smart_tv": "webOS 23",
    },
    "Samsung 55\" QLED 4K Q70C": {
        "display": "55\" 4K QLED",
        "refresh_rate": "120Hz",
        "hdr": "Quantum HDR, HDR10+",
        "processor": "Quantum Processor Lite 4K",
        "smart_tv": "Tizen",
    },
    # Apple Watch
    "Apple Watch Series 9 45mm": {
        "processor": "Apple S9 SiP",
        "display": "45mm OLED Always-On Retina",
        "battery": "до 18 часов",
        "water_resistance": "WR50 (50 метров)",
    },
    # Samsung Watch
    "Galaxy Watch 6 44mm": {
        "processor": "Exynos W930",
        "display": "44mm Super AMOLED, 480x480",
        "battery": "425 mAh (до 40 часов)",
        "water_resistance": "IP68, 5ATM",
    },
    # Audio
    "AirPods Pro 2 USB": {
        "driver": "Apple H2 чип",
        "anc": "Активное шумоподавление (ANC)",
        "battery": "до 6 часов (до 30 с кейсом)",
        "connectivity": "Bluetooth 5.3, USB-C",
    },
    "Sony WH-1000XM5": {
        "driver": "30mm, HD Noise Cancelling Processor QN1",
        "anc": "Активное шумоподавление (ANC)",
        "battery": "до 30 часов",
        "connectivity": "Bluetooth 5.2, USB-C, 3.5mm jack",
    },
    # JBL
    "JBL Charge 5": {
        "driver": "рейсер + 2 излучателя",
        "power": "30W",
        "battery": "до 20 часов",
        "water_resistance": "IP67",
        "connectivity": "Bluetooth 5.1",
    },
    # Anker
    "Anker MagGo 10000mAh": {
        "capacity": "10000 mAh",
        "output": "до 15W MagSafe + 20W USB-C PD",
        "connectivity": "MagSafe + USB-C",
        "weight": "220 г",
    },
}


async def run():
    async with async_session_factory() as db:
        tenant_id = "a7b1be91-b75f-4088-848a-22705b44b1b2"

        # 1. Add specs to all variants
        result = await db.execute(
            select(ProductVariant).where(ProductVariant.tenant_id == tenant_id)
        )
        variants = result.scalars().all()

        specs_updated = 0
        for v in variants:
            # Find matching specs by checking title prefix
            matched_spec = None
            for prefix, spec in SPECS.items():
                if v.title.startswith(prefix):
                    matched_spec = spec
                    break
            if matched_spec:
                # Merge with existing attributes_json if any
                existing = dict(v.attributes_json) if v.attributes_json else {}
                existing.update(matched_spec)
                v.attributes_json = existing
                flag_modified(v, "attributes_json")
                specs_updated += 1
                print(f"  ✅ Specs: {v.title} → {list(matched_spec.keys())}")
            else:
                print(f"  ⚠️  No specs match for: {v.title}")

        await db.flush()
        print(f"\n📋 Updated specs for {specs_updated} variants\n")

        # 2. Restock out-of-stock products (add more quantity)
        restock_map = {
            # variant title prefix → new total quantity
            "AirPods Pro 2": 10,
            "iPhone 15 Pro 256GB Black": 8,
            "iPhone 15 Pro 256GB Blue Titanium": 5,
            "iPhone 15 Pro Max 256GB Black Titanium": 5,
            "iPhone 15 Pro Max 256GB Natural Titanium": 5,
            "MacBook Pro 14 M3": 8,
        }

        restocked = 0
        for v in variants:
            for prefix, new_qty in restock_map.items():
                if v.title.startswith(prefix):
                    inv_result = await db.execute(
                        select(Inventory).where(
                            Inventory.tenant_id == tenant_id,
                            Inventory.variant_id == v.id,
                        )
                    )
                    inv = inv_result.scalar_one_or_none()
                    if inv:
                        old_avail = inv.quantity - inv.reserved_quantity
                        inv.quantity = new_qty
                        new_avail = inv.quantity - inv.reserved_quantity
                        print(f"  🔄 Restock: {v.title} | qty: {inv.quantity - (new_qty - inv.quantity)} → {new_qty} | avail: {old_avail} → {new_avail}")
                        restocked += 1
                    break

        await db.flush()
        await db.commit()
        print(f"\n📦 Restocked {restocked} variants")
        print("\n✅ Done!")


if __name__ == "__main__":
    asyncio.run(run())
