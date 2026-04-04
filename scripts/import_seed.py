"""Import seed data from CSV files into the database.

Maps integer CSV IDs to UUIDs and imports in FK order.
"""

import asyncio
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, ".")

from src.core.database import async_session_factory, engine, Base
from src.core.security import hash_password
from src.tenants.models import Tenant
from src.auth.models import User
from src.catalog.models import (
    Category,
    DeliveryRule,
    Inventory,
    Product,
    ProductAlias,
    ProductMedia,
    ProductVariant,
)
from src.conversations.models import CommentTemplate
from src.telegram.models import TelegramAccount, TelegramChannel, TelegramDiscussionGroup
from src.ai.models import AiSettings
from src.orders.models import *  # noqa
from src.leads.models import *  # noqa
from src.handoffs.models import *  # noqa
from src.core.audit import *  # noqa

CSV_DIR = Path("ai_closer_electronics_seed_csv")

# ID mapping: csv_int_id -> uuid
id_map: dict[str, dict[int, str]] = {
    "tenants": {},
    "users": {},
    "categories": {},
    "products": {},
    "variants": {},
    "inventory": {},
    "aliases": {},
    "media": {},
    "delivery_rules": {},
    "templates": {},
    "ai_settings": {},
    "telegram_accounts": {},
    "telegram_channels": {},
    "telegram_groups": {},
}


def read_csv(filename: str) -> list[dict]:
    path = CSV_DIR / filename
    if not path.exists():
        print(f"  ⚠ {filename} not found, skipping")
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def parse_bool(val: str) -> bool:
    return val.strip().lower() in ("true", "1", "yes")


def parse_int(val: str) -> int:
    return int(val.strip())


def parse_decimal(val: str) -> Decimal:
    return Decimal(val.strip())


def parse_json_patterns(val: str) -> list:
    """Parse trigger_patterns from CSV — stored as JSON array string."""
    val = val.strip()
    if not val:
        return []
    try:
        result = json.loads(val)
        if isinstance(result, list):
            return result
        return [result]
    except json.JSONDecodeError:
        # Try fixing common CSV quoting issues
        # The CSV may have patterns like: ["+", "++", "+ цена"]
        # but with extra quotes from CSV escaping
        val = val.replace('""', '"')
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            print(f"  ⚠ Could not parse patterns: {val[:80]}")
            return [val]


async def import_all():
    # Recreate tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Tables recreated")

    async with async_session_factory() as db:
        # 1. Tenant
        rows = read_csv("tenants.csv")
        for row in rows:
            uid = uuid4()
            id_map["tenants"][parse_int(row["id"])] = uid
            tenant = Tenant(id=uid, name=row["name"], slug=row["slug"], status=row["status"])
            db.add(tenant)
        await db.flush()
        tenant_id = id_map["tenants"][1]
        print(f"✓ Tenants: {len(rows)} (id: {tenant_id})")

        # 2. Users
        rows = read_csv("users.csv")
        for row in rows:
            uid = uuid4()
            id_map["users"][parse_int(row["id"])] = uid
            user = User(
                id=uid,
                tenant_id=id_map["tenants"][parse_int(row["tenant_id"])],
                full_name=row["full_name"],
                email=row["email"].replace(".local", ".com"),
                password_hash=hash_password("admin123"),
                role=row["role"],
                is_active=parse_bool(row["is_active"]),
            )
            db.add(user)
        await db.flush()
        print(f"✓ Users: {len(rows)}")

        # 3. Categories
        rows = read_csv("categories.csv")
        for row in rows:
            uid = uuid4()
            id_map["categories"][parse_int(row["id"])] = uid
            cat = Category(
                id=uid,
                tenant_id=tenant_id,
                parent_id=id_map["categories"].get(parse_int(row["parent_id"])) if row.get("parent_id", "").strip() else None,
                name=row["name"],
                slug=row["slug"],
                is_active=parse_bool(row["is_active"]),
            )
            db.add(cat)
        await db.flush()
        print(f"✓ Categories: {len(rows)}")

        # 4. Products
        rows = read_csv("products.csv")
        for row in rows:
            uid = uuid4()
            id_map["products"][parse_int(row["id"])] = uid
            prod = Product(
                id=uid,
                tenant_id=tenant_id,
                category_id=id_map["categories"].get(parse_int(row["category_id"])) if row.get("category_id", "").strip() else None,
                brand=row.get("brand", "").strip() or None,
                model=row.get("model", "").strip() or None,
                name=row["name"],
                slug=row["slug"],
                description=row.get("description", "").strip() or None,
                is_active=parse_bool(row["is_active"]),
            )
            db.add(prod)
        await db.flush()
        print(f"✓ Products: {len(rows)}")

        # 5. Product Aliases
        rows = read_csv("product_aliases.csv")
        for row in rows:
            uid = uuid4()
            id_map["aliases"][parse_int(row["id"])] = uid
            alias = ProductAlias(
                id=uid,
                tenant_id=tenant_id,
                product_id=id_map["products"][parse_int(row["product_id"])],
                alias_text=row["alias_text"],
                priority=parse_int(row["priority"]),
            )
            db.add(alias)
        await db.flush()
        print(f"✓ Product Aliases: {len(rows)}")

        # 6. Product Variants
        rows = read_csv("product_variants.csv")
        for row in rows:
            uid = uuid4()
            id_map["variants"][parse_int(row["id"])] = uid
            attrs = row.get("attributes_json", "").strip()
            attrs_json = json.loads(attrs) if attrs else None
            variant = ProductVariant(
                id=uid,
                tenant_id=tenant_id,
                product_id=id_map["products"][parse_int(row["product_id"])],
                sku=row.get("sku", "").strip() or None,
                title=row["title"],
                color=row.get("color", "").strip() or None,
                storage=row.get("storage", "").strip() or None,
                ram=row.get("ram", "").strip() or None,
                size=row.get("size", "").strip() or None,
                attributes_json=attrs_json,
                price=parse_decimal(row["price"]),
                currency=row.get("currency", "UZS").strip(),
                is_active=parse_bool(row["is_active"]),
            )
            db.add(variant)
        await db.flush()
        print(f"✓ Product Variants: {len(rows)}")

        # 7. Inventory
        rows = read_csv("inventory.csv")
        for row in rows:
            uid = uuid4()
            id_map["inventory"][parse_int(row["id"])] = uid
            inv = Inventory(
                id=uid,
                tenant_id=tenant_id,
                variant_id=id_map["variants"][parse_int(row["variant_id"])],
                quantity=parse_int(row["quantity"]),
                reserved_quantity=parse_int(row["reserved_quantity"]),
            )
            db.add(inv)
        await db.flush()
        print(f"✓ Inventory: {len(rows)}")

        # 8. Product Media
        rows = read_csv("product_media.csv")
        for row in rows:
            uid = uuid4()
            id_map["media"][parse_int(row["id"])] = uid
            variant_csv_id = row.get("variant_id", "").strip()
            media = ProductMedia(
                id=uid,
                tenant_id=tenant_id,
                product_id=id_map["products"][parse_int(row["product_id"])],
                variant_id=id_map["variants"][parse_int(variant_csv_id)] if variant_csv_id else None,
                url=row["url"],
                media_type=row.get("media_type", "image").strip(),
                sort_order=parse_int(row.get("sort_order", "0")),
            )
            db.add(media)
        await db.flush()
        print(f"✓ Product Media: {len(rows)}")

        # 9. Delivery Rules
        rows = read_csv("delivery_rules.csv")
        for row in rows:
            uid = uuid4()
            id_map["delivery_rules"][parse_int(row["id"])] = uid
            rule = DeliveryRule(
                id=uid,
                tenant_id=tenant_id,
                city=row.get("city", "").strip() or None,
                zone=row.get("zone", "").strip() or None,
                delivery_type=row["delivery_type"],
                price=parse_decimal(row["price"]),
                eta_min_days=parse_int(row["eta_min_days"]),
                eta_max_days=parse_int(row["eta_max_days"]),
                cod_available=parse_bool(row["cod_available"]),
                pickup_available=parse_bool(row["pickup_available"]),
                is_active=parse_bool(row["is_active"]),
            )
            db.add(rule)
        await db.flush()
        print(f"✓ Delivery Rules: {len(rows)}")

        # 10. Comment Templates
        rows = read_csv("comment_templates.csv")
        for row in rows:
            uid = uuid4()
            id_map["templates"][parse_int(row["id"])] = uid
            patterns = parse_json_patterns(row["trigger_patterns"])
            tpl = CommentTemplate(
                id=uid,
                tenant_id=tenant_id,
                trigger_type=row["trigger_type"],
                trigger_patterns=patterns,
                language=row.get("language", "ru").strip(),
                template_text=row["template_text"],
                is_active=parse_bool(row["is_active"]),
            )
            db.add(tpl)
        await db.flush()
        print(f"✓ Comment Templates: {len(rows)}")

        # 11. AI Settings
        rows = read_csv("ai_settings.csv")
        for row in rows:
            uid = uuid4()
            id_map["ai_settings"][parse_int(row["id"])] = uid
            ai = AiSettings(
                id=uid,
                tenant_id=tenant_id,
                tone=row.get("tone", "friendly_sales").strip(),
                language=row.get("language", "ru").strip(),
                fallback_mode=row.get("fallback_mode", "handoff").strip(),
                allow_auto_comment_reply=parse_bool(row.get("allow_auto_comment_reply", "True")),
                allow_auto_dm_reply=parse_bool(row.get("allow_auto_dm_reply", "True")),
                require_handoff_for_unknown_product=parse_bool(row.get("require_handoff_for_unknown_product", "True")),
            )
            db.add(ai)
        await db.flush()
        print(f"✓ AI Settings: {len(rows)}")

        # 12. Telegram Account — use the real test account session
        # Skip CSV dummy data, create real entry for the connected test account
        tg_account = TelegramAccount(
            tenant_id=tenant_id,
            phone_number="+998330009250",
            display_name="TechnoUz AI",
            username=None,
            session_ref=f"{tenant_id}_+998330009250",
            status="connected",
            is_primary=True,
        )
        db.add(tg_account)
        await db.flush()
        print(f"✓ Telegram Account: +998330009250 (session_ref: {tg_account.session_ref})")

        await db.commit()
        print("\n✅ All seed data imported successfully!")
        print(f"\n  Tenant ID: {tenant_id}")
        print(f"  Login: owner@technouz-demo.local / admin123")
        print(f"  Login: admin@technouz-demo.local / admin123")

        # Verify counts
        from sqlalchemy import func, select
        tables = [
            ("tenants", Tenant),
            ("users", User),
            ("categories", Category),
            ("products", Product),
            ("product_aliases", ProductAlias),
            ("product_variants", ProductVariant),
            ("inventory", Inventory),
            ("product_media", ProductMedia),
            ("delivery_rules", DeliveryRule),
            ("comment_templates", CommentTemplate),
            ("ai_settings", AiSettings),
            ("telegram_accounts", TelegramAccount),
        ]
        print("\n--- Verification ---")
        for name, model in tables:
            result = await db.execute(select(func.count()).select_from(model))
            count = result.scalar()
            print(f"  {name}: {count}")


if __name__ == "__main__":
    asyncio.run(import_all())
