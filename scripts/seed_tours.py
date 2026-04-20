"""Seed script for Easy Tour — creates tenant, user, categories, tours, variants, aliases, inventory, AI settings."""

import asyncio
import json
import sys
from uuid import uuid4

sys.path.insert(0, ".")

from src.core.database import engine, async_session_factory, Base
from src.core.security import hash_password
from src.tenants.models import Tenant
from src.auth.models import User
from src.catalog.models import Category, Product, ProductVariant, ProductAlias, Inventory
from src.ai.models import AiSettings

# Import all models so tables are registered
from src.telegram.models import *  # noqa
from src.conversations.models import *  # noqa
from src.leads.models import *  # noqa
from src.orders.models import *  # noqa
from src.handoffs.models import *  # noqa
from src.core.audit import *  # noqa


def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace("'", "").replace("ʼ", "")


# ── Categories ──
CATEGORIES = [
    {"name": "Yengil yurish", "aliases": ["лёгкий", "легкий", "easy hike", "yengil", "oson"]},
    {"name": "O'rta yurish", "aliases": ["средний", "medium hike", "orta", "ўрта"]},
    {"name": "Adrenalin", "aliases": ["экстрим", "адреналин", "extreme", "adrenaline"]},
    {"name": "4x4 tur", "aliases": ["джип", "внедорожник", "jeep", "off-road", "4x4"]},
    {"name": "Kemping", "aliases": ["кемпинг", "палатка", "camping", "camp"]},
    {"name": "Ko'p kunlik", "aliases": ["многодневный", "multi-day", "3 kun", "2 kun", "кўп кунлик"]},
    {"name": "Tadbirlar", "aliases": ["мероприятие", "event", "party", "tadbir", "тадбир"]},
    {"name": "Xalqaro", "aliases": ["международный", "international", "chet el", "чет эл", "халқаро"]},
]

# ── Tours (Product = Tour, brand=difficulty, model=duration) ──
TOURS = [
    {
        "name": "Paltau sharshara",
        "brand": "Yengil",  # difficulty
        "model": "1 kun",   # duration
        "category": "Yengil yurish",
        "description": "Paltau sharsharasiga sayohat. Toshkentdan 1.5 soat. Tabiat qo'ynida dam olish, suv yonida piknik.",
        "aliases": ["палтау", "paltov", "paltau waterfall", "paltaw", "палтоу"],
        "variants": [
            {
                "title": "19-aprel Paltau",
                "color": "2026-04-19",      # departure_date
                "storage": "08:00",          # departure_time
                "price": 199000,
                "seats": 30,
                "details": {"meeting_point": "Chorsu metro", "included": "Transport, guide, piknik", "what_to_bring": "Qulay kiyim, suv, quyosh ko'zoynak"},
            },
            {
                "title": "26-aprel Paltau",
                "color": "2026-04-26",
                "storage": "08:00",
                "price": 199000,
                "seats": 30,
                "details": {"meeting_point": "Chorsu metro", "included": "Transport, guide, piknik", "what_to_bring": "Qulay kiyim, suv, quyosh ko'zoynak"},
            },
        ],
    },
    {
        "name": "Chukuraksu sharshara",
        "brand": "Yengil",
        "model": "1 kun",
        "category": "Yengil yurish",
        "description": "Chukuraksu sharsharasiga yengil trek. Chiroyli tog' manzarasi va toza havo.",
        "aliases": ["чукуракcу", "chukurak", "chukuraksu waterfall", "чукурак"],
        "variants": [
            {
                "title": "20-aprel Chukuraksu",
                "color": "2026-04-20",
                "storage": "07:30",
                "price": 199000,
                "seats": 25,
                "details": {"meeting_point": "Buyuk Ipak Yo'li metro", "included": "Transport, guide", "what_to_bring": "Suv, qulay oyoq kiyim"},
            },
            {
                "title": "3-may Chukuraksu",
                "color": "2026-05-03",
                "storage": "07:30",
                "price": 199000,
                "seats": 25,
                "details": {"meeting_point": "Buyuk Ipak Yo'li metro", "included": "Transport, guide", "what_to_bring": "Suv, qulay oyoq kiyim"},
            },
        ],
    },
    {
        "name": "Ispay sharshara",
        "brand": "Yengil",
        "model": "1 kun",
        "category": "Yengil yurish",
        "description": "Ispay sharsharasi — eng chiroyli sharsharalardan biri. Trekking + piknik.",
        "aliases": ["испай", "ispay waterfall", "ispai"],
        "variants": [
            {
                "title": "25-aprel Ispay",
                "color": "2026-04-25",
                "storage": "07:00",
                "price": 250000,
                "seats": 25,
                "details": {"meeting_point": "Oybek metro", "included": "Transport, guide, tushlik", "what_to_bring": "Trek kiyim, suv 1.5L"},
            },
        ],
    },
    {
        "name": "Chimgan tog' yurish",
        "brand": "O'rta",
        "model": "1 kun",
        "category": "O'rta yurish",
        "description": "Chimgan tog'iga o'rta darajadagi trek. 2000m balandlik, ajoyib panorama.",
        "aliases": ["чимган", "chimgan", "chimgon", "чимгон"],
        "variants": [
            {
                "title": "19-aprel Chimgan",
                "color": "2026-04-19",
                "storage": "06:30",
                "price": 280000,
                "seats": 20,
                "details": {"meeting_point": "Chorsu metro", "included": "Transport, guide, tushlik", "what_to_bring": "Trek oyoq kiyim, issiq kiyim, suv 2L"},
            },
            {
                "title": "3-may Chimgan",
                "color": "2026-05-03",
                "storage": "06:30",
                "price": 280000,
                "seats": 20,
                "details": {"meeting_point": "Chorsu metro", "included": "Transport, guide, tushlik", "what_to_bring": "Trek oyoq kiyim, issiq kiyim, suv 2L"},
            },
        ],
    },
    {
        "name": "Oqtosh tog' yurish",
        "brand": "O'rta",
        "model": "1 kun",
        "category": "O'rta yurish",
        "description": "Oqtosh tog'iga trek — tog' daryosi, ko'priklar, tabiat. Jismoniy tayyorgarlik talab qilinadi.",
        "aliases": ["оқтош", "oqtash", "aktash", "ок тош", "oqtosh trek"],
        "variants": [
            {
                "title": "26-aprel Oqtosh",
                "color": "2026-04-26",
                "storage": "06:00",
                "price": 350000,
                "seats": 20,
                "details": {"meeting_point": "Chorsu metro", "included": "Transport, guide, tushlik, sug'urta", "what_to_bring": "Trek oyoq kiyim, ryukzak, suv 2L, snack"},
            },
        ],
    },
    {
        "name": "Bungee jumping",
        "brand": "Adrenalin",
        "model": "Yarim kun",
        "category": "Adrenalin",
        "description": "Bungee jumping — Charvak to'g'onidan sakrash! 45m balandlik. Professional xavfsizlik jihozlari.",
        "aliases": ["банжи", "bungee", "банджи", "прыжок", "sakrash"],
        "variants": [
            {
                "title": "20-aprel Bungee",
                "color": "2026-04-20",
                "storage": "10:00",
                "price": 500000,
                "seats": 15,
                "details": {"meeting_point": "Charvak to'g'oni", "included": "Jihoz, instruktor, sertifikat", "what_to_bring": "Qulay kiyim, krossovka"},
            },
        ],
    },
    {
        "name": "Zipline + Kayak",
        "brand": "Adrenalin",
        "model": "1 kun",
        "category": "Adrenalin",
        "description": "Zipline 500m + kayak Charvak ko'lida. Ikki adrenalin bir kunda!",
        "aliases": ["зиплайн", "zipline", "kayak", "каяк", "зиплайн каяк"],
        "variants": [
            {
                "title": "19-aprel Zipline+Kayak",
                "color": "2026-04-19",
                "storage": "09:00",
                "price": 550000,
                "seats": 20,
                "details": {"meeting_point": "Charvak", "included": "Jihoz, instruktor, transport, tushlik", "what_to_bring": "Almashtirish kiyim, sochiq"},
            },
        ],
    },
    {
        "name": "Nefrit ko'l 4x4",
        "brand": "O'rta",
        "model": "1 kun",
        "category": "4x4 tur",
        "description": "Nefrit ko'liga 4x4 sayohat. Tog' yo'llari, ajoyib ko'l, piknik.",
        "aliases": ["нефрит", "nefrit", "нефрит озеро", "nefrit kol"],
        "variants": [
            {
                "title": "26-aprel Nefrit 4x4",
                "color": "2026-04-26",
                "storage": "07:00",
                "price": 450000,
                "seats": 15,
                "details": {"meeting_point": "Chorsu metro", "included": "4x4 transport, guide, tushlik", "what_to_bring": "Issiq kiyim, suv"},
            },
        ],
    },
    {
        "name": "Tuzkon kemping",
        "brand": "Yengil",
        "model": "2 kun / 1 tun",
        "category": "Kemping",
        "description": "Tuzkon ko'lida kemping — yulduzlar ostida tunash, tog' havosi, go'sht kabob.",
        "aliases": ["тузкон", "tuzkan", "кемпинг тузкон", "kemping"],
        "variants": [
            {
                "title": "19-20 aprel Tuzkon kemping",
                "color": "2026-04-19",
                "storage": "15:00",
                "price": 699000,
                "seats": 25,
                "details": {"meeting_point": "Chorsu metro", "included": "Transport, chodir, uyqu qopi, kechki ovqat, nonushta, guide", "what_to_bring": "Issiq kiyim, fonar, shaxsiy buyumlar"},
            },
        ],
    },
    {
        "name": "Xiva sayohat",
        "brand": "O'rta",
        "model": "3 kun / 2 tun",
        "category": "Ko'p kunlik",
        "description": "Xiva tarixiy shaharga sayohat. Ichan Qal'a, madrasalar, mahalliy oshxona. Mehmonxonada tunash.",
        "aliases": ["хива", "xiva", "хиво", "khiva"],
        "variants": [
            {
                "title": "1-3 may Xiva",
                "color": "2026-05-01",
                "storage": "22:00",
                "price": 999000,
                "seats": 20,
                "details": {"meeting_point": "Toshkent temir yo'l vokzali", "included": "Poyezd, mehmonxona, nonushta, guide, ekskursiya", "what_to_bring": "Qulay oyoq kiyim, quyosh kremi"},
            },
        ],
    },
    {
        "name": "Mewa Party",
        "brand": "Yengil",
        "model": "Yarim kun",
        "category": "Tadbirlar",
        "description": "Meva festivali — 10+ meva degustatsiiyasi, musiqa, konkurslar, bolalar uchun joy.",
        "aliases": ["мева", "meva", "мева пати", "meva party", "festival"],
        "variants": [
            {
                "title": "3-may Mewa Party",
                "color": "2026-05-03",
                "storage": "11:00",
                "price": 400000,
                "seats": 130,
                "details": {"meeting_point": "Toshkent, Navruz bog'i", "included": "Mevalar, dastur, musiqiy dastur", "what_to_bring": "Yaxshi kayfiyat!"},
            },
        ],
    },
    {
        "name": "Qirg'iziston sayohat",
        "brand": "O'rta",
        "model": "5 kun / 4 tun",
        "category": "Xalqaro",
        "description": "Qirg'iziston — Issiqko'l, Bishkek, tog' treking. Yurt kemping va at minish.",
        "aliases": ["кыргызстан", "qirgiziston", "киргизия", "kyrgyzstan", "issiqkol", "иссык-куль"],
        "variants": [
            {
                "title": "9-13 may Qirg'iziston",
                "color": "2026-05-09",
                "storage": "06:00",
                "price": 2280000,
                "seats": 20,
                "details": {"meeting_point": "Toshkent aeroporti", "included": "Avia, mehmonxona, yurt, ovqat, guide, transport", "what_to_bring": "Zagran pasport, issiq kiyim, trek oyoq kiyim"},
            },
        ],
    },
]


async def seed():
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        from sqlalchemy import text as sql_text

        # ── Check if Easy Tour tenant already exists ──
        result = await db.execute(
            sql_text("SELECT id FROM tenants WHERE slug = 'easy-tour'")
        )
        existing = result.first()
        if existing:
            tid = existing[0]
            # Clean old data to re-seed
            await db.execute(sql_text("DELETE FROM inventory WHERE tenant_id = :tid"), {"tid": tid})
            await db.execute(sql_text("DELETE FROM product_aliases WHERE tenant_id = :tid"), {"tid": tid})
            await db.execute(sql_text("DELETE FROM product_variants WHERE tenant_id = :tid"), {"tid": tid})
            await db.execute(sql_text("DELETE FROM products WHERE tenant_id = :tid"), {"tid": tid})
            await db.execute(sql_text("DELETE FROM categories WHERE tenant_id = :tid"), {"tid": tid})
            await db.execute(sql_text("DELETE FROM ai_settings WHERE tenant_id = :tid"), {"tid": tid})
            await db.flush()
            print(f"  Re-seeding existing Easy Tour tenant {tid}")
        else:
            # ── Create NEW tenant (keep existing TechnoUz intact!) ──
            tenant = Tenant(name="Easy Tour", slug="easy-tour", status="active")
            db.add(tenant)
            await db.flush()
            tid = tenant.id

            admin = User(
                tenant_id=tid,
                full_name="Easy Tour Admin",
                email="easytour@admin.com",
                password_hash=hash_password("admin"),
                role="store_owner",
            )
            db.add(admin)
            await db.flush()
            print(f"  Created NEW tenant Easy Tour ({tid})")

        # ── Categories ──
        cat_map = {}
        for cat in CATEGORIES:
            c = Category(tenant_id=tid, name=cat["name"], slug=slugify(cat["name"]))
            db.add(c)
            await db.flush()
            cat_map[cat["name"]] = c.id

            # Category aliases as product aliases won't work — categories are matched by name
            # The truth_tools.py has CATEGORY_NAME_ALIASES for this

        # ── Tours + Variants + Aliases + Inventory ──
        total_tours = 0
        total_variants = 0
        total_aliases = 0

        for tour_data in TOURS:
            cat_id = cat_map.get(tour_data["category"])
            product = Product(
                tenant_id=tid,
                name=tour_data["name"],
                slug=slugify(tour_data["name"]),
                description=tour_data.get("description"),
                brand=tour_data.get("brand"),
                model=tour_data.get("model"),
                category_id=cat_id,
                is_active=True,
            )
            db.add(product)
            await db.flush()
            total_tours += 1

            # Aliases
            aliases = [tour_data["name"].lower()]
            for a in tour_data.get("aliases", []):
                if a.lower() not in aliases:
                    aliases.append(a.lower())

            for i, alias_text in enumerate(aliases):
                alias = ProductAlias(
                    tenant_id=tid,
                    product_id=product.id,
                    alias_text=alias_text,
                    priority=10 - i,
                )
                db.add(alias)
                total_aliases += 1

            # Variants + Inventory
            for v_data in tour_data.get("variants", []):
                details = v_data.get("details", {})
                variant = ProductVariant(
                    tenant_id=tid,
                    product_id=product.id,
                    title=v_data["title"],
                    color=v_data.get("color"),        # departure_date
                    storage=v_data.get("storage"),      # departure_time
                    price=v_data["price"],
                    currency="UZS",
                    is_active=True,
                    attributes_json=details if details else None,
                )
                db.add(variant)
                await db.flush()
                total_variants += 1

                # Inventory (seats)
                inv = Inventory(
                    tenant_id=tid,
                    variant_id=variant.id,
                    quantity=v_data.get("seats", 20),
                    reserved_quantity=0,
                )
                db.add(inv)

        # ── AI Settings ──
        ai_settings = AiSettings(
            tenant_id=tid,
            allow_auto_dm_reply=True,
            allow_auto_comment_reply=True,
            allow_ai_cancel_draft=True,
            require_operator_for_edit=False,
            require_handoff_for_unknown_product=True,
            max_variants_in_reply=5,
            confirm_before_order=True,
            tone="friendly_sales",
            language="uz_latin",
            fallback_mode="handoff",
            channel_show_price=True,
        )
        db.add(ai_settings)

        await db.commit()

        print(f"\n{'='*50}")
        print(f"  Easy Tour — Seed Data Created!")
        print(f"{'='*50}")
        print(f"  Tenant ID: {tid}")
        print(f"  Admin:  easytour@admin.com / admin")
        print(f"  Categories: {len(CATEGORIES)}")
        print(f"  Tours: {total_tours}")
        print(f"  Variants (dates): {total_variants}")
        print(f"  Aliases: {total_aliases}")
        print(f"  AI language: uz_latin")
        print(f"{'='*50}\n")


if __name__ == "__main__":
    asyncio.run(seed())
