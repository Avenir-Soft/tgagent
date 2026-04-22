"""Truth tools layer — deterministic data access for AI agent.

These are NOT LLM calls. They return factual data from the database.
The AI agent calls these tools to get price, stock, delivery, etc.
"""

import hashlib
import json as _json
import logging
import time as _time
import uuid as uuid_mod
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, union_all, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.catalog.models import Category, DeliveryRule, Inventory, Product, ProductAlias, ProductMedia, ProductVariant
from src.leads.models import Lead
from src.orders.models import Order, OrderItem

_logger = logging.getLogger(__name__)

# ── Cache layer ───────────────────────────────────────────────────────────────
# Categories: in-memory (small data, rarely changes) — TTL 5 min
_cat_cache: dict[str, tuple[dict, float]] = {}
_CAT_TTL = 300

# Product search: Redis (varied queries, larger data) — TTL 3 min
_SEARCH_TTL = 180
_redis_cache = None


async def _get_cache_redis():
    global _redis_cache
    if _redis_cache is None:
        from src.core.redis import get_redis
        _redis_cache = get_redis()
    return _redis_cache


async def _search_cache_get(tenant_id: UUID, query: str) -> dict | None:
    try:
        r = await _get_cache_redis()
        key = f"cat_srch:{tenant_id}:{hashlib.md5(query.lower().strip().encode()).hexdigest()}"
        data = await r.get(key)
        return _json.loads(data) if data else None
    except Exception as e:
        _logger.warning("Redis cache GET failed for tenant %s: %s", tenant_id, e)
        return None


async def _search_cache_set(tenant_id: UUID, query: str, result: dict) -> None:
    try:
        r = await _get_cache_redis()
        key = f"cat_srch:{tenant_id}:{hashlib.md5(query.lower().strip().encode()).hexdigest()}"
        await r.setex(key, _SEARCH_TTL, _json.dumps(result, default=str))
    except Exception as e:
        _logger.warning("Redis cache SET failed for tenant %s: %s", tenant_id, e)


async def invalidate_catalog_cache(tenant_id) -> None:
    """Invalidate categories in-memory cache AND Redis search cache."""
    _cat_cache.pop(str(tenant_id), None)
    try:
        r = await _get_cache_redis()
        prefix = f"cat_srch:{tenant_id}:"
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=f"{prefix}*", count=100)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        _logger.warning("Redis cache invalidation failed for tenant %s: %s", tenant_id, e)


def _escape_like(s: str) -> str:
    """Escape SQL LIKE/ILIKE wildcard characters in user input."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


CATEGORY_NAME_ALIASES: dict[str, list[str]] = {
    # Keys MUST match actual DB category names (Russian)
    "Аксессуары": [
        "аксессуары", "аксессуар", "зарядка", "кабель", "чехол", "повербанк",
        "aksessuar", "zaryadka", "chexol", "accessories",
    ],
    "Аудио": [
        "аудио", "звук", "наушники", "колонка", "колонки",
        "audio", "ovoz", "musiqa", "quloqchin", "naushnik",
    ],
    "Игровые устройства": [
        "игры", "игровые", "приставка", "приставки", "консоль", "консоли", "гейминг",
        "o'yin", "pristavka", "konsol", "gaming", "game", "поиграть",
    ],
    "Ноутбуки": [
        "ноутбуки", "ноутбук", "ноут", "лэптоп",
        "noutbuk", "nout", "laptop", "notebook",
    ],
    "Смартфоны": [
        "смартфоны", "смартфон", "телефон", "телефоны", "мобильный",
        "telefon", "smartfon", "mobil", "phone", "smartphone",
    ],
    "Планшеты": [
        "планшеты", "планшет",
        "planshet", "tablet", "ipad",
    ],
    "ТВ и развлечения": [
        "телевизор", "телевизоры", "тв и развлечение", "развлечение", "телек",
        "televizor", "tv", "television",
    ],
    "Умные часы": [
        "умные устройства", "часы", "смарт-часы", "браслет", "носимые",
        "soat", "aqlli soat", "smart soat", "watch", "smartwatch",
    ],
}


PRODUCT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "headphones": ["airpods", "wh-1000", "wh1000", "wf-1000", "headphone", "наушники", "buds", "earbuds", "earpods", "quloqchin"],
    "speaker": ["charge", "flip", "boom", "колонка", "speaker", "портативная", "karnay", "soundbar"],
    "smartphone": ["iphone", "galaxy s", "redmi", "pixel", "телефон", "smartfon"],
    "laptop": ["macbook", "zenbook", "legion", "ideapad", "thinkpad", "ноутбук", "noutbuk"],
    "tablet": ["ipad", "tab s", "планшет", "planshet"],
    "smartwatch": ["watch", "часы", "soat"],
    "tv": ["oled c", "qled", "телевизор", "televizor"],
    "gaming_console": ["playstation", "xbox", "nintendo", "приставка", "konsol"],
    "accessory": ["anker", "magsafe", "зарядка", "кабель", "чехол", "повербанк"],
}


def _classify_product_type(name: str, model: str, category: str) -> str:
    """Classify product into a specific type based on name/model keywords."""
    combined = f"{name} {model}".lower()
    for ptype, keywords in PRODUCT_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return ptype
    return category.lower() if category else "other"


async def list_categories(tenant_id: UUID, db: AsyncSession) -> dict:
    """List all active product categories with product counts (cached 5 min)."""
    key = str(tenant_id)
    cached = _cat_cache.get(key)
    if cached and _time.monotonic() - cached[1] < _CAT_TTL:
        return cached[0]

    result = await db.execute(
        select(Category, func.count(Product.id).label("product_count"))
        .outerjoin(Product, (Product.category_id == Category.id) & Product.is_active.is_(True) & (Product.tenant_id == tenant_id))
        .where(
            Category.tenant_id == tenant_id,
            Category.is_active.is_(True),
        )
        .group_by(Category.id)
        .order_by(Category.name)
    )

    cat_list = []
    for cat, count in result.all():
        if count > 0:
            aliases = CATEGORY_NAME_ALIASES.get(cat.name, [])
            display_name = aliases[0].capitalize() if aliases else cat.name
            cat_list.append({
                "name": cat.name,
                "display_name": display_name,
                "search_aliases": aliases,
                "product_count": count,
            })

    data = {"categories": cat_list, "total_categories": len(cat_list)}
    _cat_cache[key] = (data, _time.monotonic())
    return data


async def get_product_candidates(tenant_id: UUID, query: str, db: AsyncSession) -> dict:
    """Search products by ILIKE on product.name, product_alias.alias_text, product_variant.title,
    category.name, product.brand, product.model.

    Splits query into words and searches each word separately for better fuzzy matching.
    Returns up to 15 matching products ranked by relevance (name match > brand/model > category).
    """
    # Search with full query + each word separately for better matching
    search_terms = [query.strip()]
    words = query.strip().split()
    if len(words) > 1:
        search_terms.extend([w for w in words if len(w) >= 2])

    # Add stemmed forms for Russian plurals (айфоны→айфон, наушники→наушник, часы→час)
    _ru_suffixes = ("ы", "и", "ов", "ей", "ами", "ях", "ам", "ов")
    stemmed = []
    for w in search_terms:
        wl = w.lower().rstrip("?!.,;:")
        if len(wl) >= 4:
            for suf in sorted(_ru_suffixes, key=len, reverse=True):
                if wl.endswith(suf) and len(wl) - len(suf) >= 3:
                    stemmed.append(wl[: -len(suf)])
                    break
    search_terms.extend(stemmed)

    # Resolve category aliases (Russian/Uzbek → English DB names)
    # Check both directions: query matches alias OR alias is prefix/substring of query
    # e.g. "laptops" should match alias "laptop", "телефоны" should match "телефон"
    q_lower = query.strip().lower()
    for db_name, aliases in CATEGORY_NAME_ALIASES.items():
        if q_lower in aliases or any(q_lower in a or a in q_lower for a in aliases):
            search_terms.append(db_name)

    # Check Redis cache first
    cached_result = await _search_cache_get(tenant_id, query)
    if cached_result is not None:
        return cached_result

    # Build ALL subqueries for ALL terms in one pass — single DB round-trip
    all_subqueries = []
    for term in search_terms:
        like_pattern = f"%{_escape_like(term)}%"

        all_subqueries.append(
            select(Product.id.label("pid"))
            .where(Product.tenant_id == tenant_id, Product.is_active.is_(True), Product.name.ilike(like_pattern))
        )
        all_subqueries.append(
            select(ProductAlias.product_id.label("pid"))
            .where(ProductAlias.tenant_id == tenant_id, ProductAlias.alias_text.ilike(like_pattern))
        )
        all_subqueries.append(
            select(ProductVariant.product_id.label("pid"))
            .where(ProductVariant.tenant_id == tenant_id, ProductVariant.is_active.is_(True), ProductVariant.title.ilike(like_pattern))
        )
        all_subqueries.append(
            select(Product.id.label("pid"))
            .join(Category, Product.category_id == Category.id)
            .where(Product.tenant_id == tenant_id, Product.is_active.is_(True), Category.name.ilike(like_pattern))
        )
        all_subqueries.append(
            select(Product.id.label("pid"))
            .where(Product.tenant_id == tenant_id, Product.is_active.is_(True), Product.brand.ilike(like_pattern))
        )
        all_subqueries.append(
            select(Product.id.label("pid"))
            .where(Product.tenant_id == tenant_id, Product.is_active.is_(True), Product.model.ilike(like_pattern))
        )

    matching_ids = union_all(*all_subqueries).subquery()
    result = await db.execute(select(matching_ids.c.pid).distinct())
    all_product_ids = set(result.scalars().all())

    if not all_product_ids:
        empty = {"found": False, "products": []}
        await _search_cache_set(tenant_id, query, empty)
        return empty

    # Fetch full product data with inventory (limit 15 to avoid dropping relevant matches)
    result = await db.execute(
        select(Product)
        .where(
            Product.id.in_(list(all_product_ids)),
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
        )
        .options(
            selectinload(Product.variants).selectinload(ProductVariant.inventory),
            selectinload(Product.variants).selectinload(ProductVariant.media),
            selectinload(Product.category),
            selectinload(Product.media),
        )
        .limit(15)
    )
    products = result.scalars().unique().all()

    if not products:
        return {"found": False, "products": []}

    product_list = []
    for p in products:
        active_variants = [v for v in p.variants if v.is_active]
        total_stock = 0
        prices = []
        for v in active_variants:
            # inventory is a list (one-to-many), but typically one record per variant
            for inv in (v.inventory or []):
                avail = max(0, (inv.quantity or 0) - (inv.reserved_quantity or 0))
                total_stock += avail
            if v.price:
                prices.append(float(v.price))
        # First product image (sorted by sort_order)
        media_sorted = sorted((p.media or []), key=lambda m: m.sort_order)
        image_url = media_sorted[0].url if media_sorted else None

        # Count ALL unique photo URLs (product-level + variant-level)
        _all_photo_urls = set()
        for m in media_sorted:
            if m.url:
                _all_photo_urls.add(m.url)
        for v in active_variants:
            for m in (v.media or []):
                if m.url:
                    _all_photo_urls.add(m.url)

        product_list.append({
            "product_id": str(p.id),
            "name": p.name,
            "brand": p.brand,
            "model": p.model,
            "category": p.category.name if p.category else None,
            "product_type": _classify_product_type(p.name, p.model or "", p.category.name if p.category else ""),
            "variants_count": len(active_variants),
            "price_range": f"{min(prices):.0f}–{max(prices):.0f}" if prices else None,
            "currency": active_variants[0].currency if active_variants and active_variants[0].currency else "UZS",
            "in_stock": total_stock > 0,
            "image_url": image_url,
            "total_photos": len(_all_photo_urls),
        })

    # Rank by relevance: exact name match > name contains > brand/model match > category match
    q_lower = query.strip().lower()
    def _relevance(p):
        name_l = (p["name"] or "").lower()
        brand_l = (p.get("brand") or "").lower()
        model_l = (p.get("model") or "").lower()
        if name_l == q_lower:
            return 0  # exact name match
        if q_lower in name_l or name_l in q_lower:
            return 1  # name contains query or vice versa
        if q_lower in brand_l or q_lower in model_l:
            return 2  # brand/model match
        return 3  # category/alias match

    product_list.sort(key=_relevance)

    in_stock = [p for p in product_list if p["in_stock"]]
    out_of_stock = [p for p in product_list if not p["in_stock"]]

    result = {
        "found": len(in_stock) > 0 or len(out_of_stock) > 0,
        "products": in_stock,
    }
    if out_of_stock:
        result["out_of_stock_products"] = out_of_stock
        categories = set(p.get("category") for p in out_of_stock if p.get("category"))
        if categories:
            result["suggestion"] = f"These products exist but are out of stock. Mention them to the customer and suggest alternatives in: {', '.join(categories)}"

    # Cache result in Redis (TTL 3 min)
    await _search_cache_set(tenant_id, query, result)
    return result


async def get_variant_candidates(tenant_id: UUID, product_id: UUID, db: AsyncSession) -> dict:
    """List active variants for a product with title, color, storage, ram, size, price, currency, in_stock."""
    result = await db.execute(
        select(ProductVariant)
        .where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.product_id == product_id,
            ProductVariant.is_active.is_(True),
        )
        .options(selectinload(ProductVariant.media))
    )
    variants = result.scalars().unique().all()

    if not variants:
        return {"found": False, "variants": [], "image_urls": []}

    # Also load product-level media (fallback if variants have no images)
    prod_result = await db.execute(
        select(Product)
        .where(Product.id == product_id, Product.tenant_id == tenant_id)
        .options(selectinload(Product.media))
    )
    product = prod_result.scalar_one_or_none()
    product_media = sorted((product.media or []) if product else [], key=lambda m: m.sort_order)

    # Batch-load all inventories in one query (fixes N+1)
    variant_ids = [v.id for v in variants]
    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.tenant_id == tenant_id,
            Inventory.variant_id.in_(variant_ids),
        )
    )
    inv_map = {inv.variant_id: inv for inv in inv_result.scalars().all()}

    variant_list = []
    product_image_urls = [m.url for m in product_media if m.url]
    for v in variants:
        inv = inv_map.get(v.id)
        available_qty = inv.available_quantity if inv else 0

        # Collect variant-level images
        variant_media = sorted((v.media or []), key=lambda m: m.sort_order)
        variant_image_urls = [m.url for m in variant_media if m.url]
        # Fallback to product-level images if variant has none
        if not variant_image_urls:
            variant_image_urls = product_image_urls

        entry = {
            "variant_id": str(v.id),
            "title": v.title,
            "color": v.color,
            "storage": v.storage,
            "ram": v.ram,
            "size": v.size,
            "price": str(v.price),
            "currency": v.currency,
            "in_stock": available_qty > 0,
            "image_urls": variant_image_urls,
            "photo_count": len(variant_image_urls),
        }
        # Include extra specs (processor, screen, battery, etc.) if present
        if v.attributes_json:
            entry["specs"] = v.attributes_json
        variant_list.append(entry)

    return {"found": True, "variants": variant_list}


async def get_variant_price(tenant_id: UUID, variant_id: UUID, db: AsyncSession) -> dict:
    """Get exact price for a specific variant."""
    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id,
            ProductVariant.tenant_id == tenant_id,
        )
    )
    variant = result.scalar_one_or_none()

    if not variant:
        return {"found": False, "error": "variant_not_found"}

    return {
        "found": True,
        "variant_id": str(variant.id),
        "title": variant.title,
        "price": str(variant.price),
        "currency": variant.currency,
    }


async def get_variant_stock(tenant_id: UUID, variant_id: UUID, db: AsyncSession) -> dict:
    """Get stock / available quantity for a specific variant."""
    result = await db.execute(
        select(Inventory).where(
            Inventory.tenant_id == tenant_id,
            Inventory.variant_id == variant_id,
        )
    )
    inv = result.scalar_one_or_none()

    if not inv:
        return {"found": False, "in_stock": False, "available_quantity": 0}

    return {
        "found": True,
        "variant_id": str(variant_id),
        "in_stock": inv.available_quantity > 0,
        "available_quantity": inv.available_quantity,
    }


CITY_ALIASES: dict[str, list[str]] = {
    "Tashkent": [
        # Russian (nominative + declensions + informal + typos)
        "ташкент", "ташкенте", "ташкенту", "ташкента", "ташкентом",
        "таш", "тошкент", "такент", "ташент", "ташкен", "тошкен",
        # Uzbek Latin
        "tashkent", "toshkent", "tosh",
        # Uzbek Cyrillic
        "тошкент", "тошкентга", "тошкентда",
        # English short
        "tash",
        # Районы Ташкента (Russian + Uzbek + Latin + typos)
        "юнусобод", "юнусабад", "yunusabad", "yunusobod",
        "чиланзар", "чилонзор", "чилонзар", "чиланзор", "chilanzar", "chilonzor",
        "мирзо улугбек", "мирзо-улугбек", "mirzo ulugbek", "мирзо улуғбек",
        "яккасарай", "яккасарой", "yakkasaray", "яккасарой",
        "шайхантахур", "шайхонтоҳур", "shayxontohur", "шахантахур",
        "алмазар", "олмазор", "olmazar", "олмозор",
        "мирабад", "мирободе", "mirabad", "мирзо обод",
        "бектемир", "bektemir", "бектемир",
        "сергели", "sergeli", "сергили",
        "учтепа", "учтепе", "uchtepa",
        "яшнабад", "яшнободе", "yashnabad", "yashnobod",
        "кибрай", "kibray",
    ],
    "Samarkand": [
        "самарканд", "самарканде", "самарканду", "самарканда", "самаркан",
        "samarkand", "samarqand",
        "самарқанд", "самарқандга", "самарқандда",
    ],
    "Bukhara": [
        "бухара", "бухаре", "бухару", "бухары", "бухарой",
        "bukhara", "buxoro",
        "бухоро", "бухорога", "бухорода",
    ],
    "Fergana": [
        "фергана", "фергане", "фергану", "ферганы", "ферганой",
        "fergana", "fargona",
        "фарғона", "фарғонага", "фарғонада",
    ],
    "Namangan": [
        "наманган", "намангане", "намангану", "намангана",
        "namangan",
        "наманган", "наманганга", "наманганда",
    ],
    "Andijan": [
        "андижан", "андижане", "андижану", "андижана",
        "andijan", "andijon",
        "андижон", "андижонга", "андижонда",
    ],
    "Nukus": [
        "нукус", "нукусе", "нукусу",
        "nukus",
        "нукус", "нукусга", "нукусда",
    ],
    "Karshi": [
        "карши", "каршие", "каршида",
        "karshi", "qarshi",
        "қарши", "қаршига", "қаршида",
    ],
    "Navoi": [
        "навои", "навоие",
        "navoi", "navoiy",
        "навоий", "навоийга", "навоийда",
    ],
    "Jizzakh": [
        "джизак", "жизак", "жизаке", "джизаке",
        "jizzakh", "jizzax",
        "жиззах", "жиззахга", "жиззахда",
    ],
    "Urgench": [
        "ургенч", "ургенче", "ургенчу",
        "urgench", "urganch",
        "урганч", "урганчга", "урганчда",
    ],
    "Termez": [
        "термез", "термезе", "термезу",
        "termez", "termiz",
        "термиз", "термизга", "термизда",
    ],
}


def _resolve_city(query: str) -> list[str]:
    """Resolve a city query to possible DB city names using aliases."""
    q = query.strip().lower()
    # Try full query first, then each word
    search_terms = [q] + [w for w in q.split() if len(w) >= 3]
    matches = set()
    for term in search_terms:
        for db_name, aliases in CITY_ALIASES.items():
            if term in aliases or db_name.lower() == term or db_name.lower().startswith(term) or any(term in a for a in aliases):
                matches.add(db_name)
    return list(matches)


async def get_delivery_options(tenant_id: UUID, city: str, db: AsyncSession) -> dict:
    """Get delivery options for a city. Supports Russian/English/Uzbek city names."""
    resolved = _resolve_city(city)

    rules = []

    # Try resolved city names first
    if resolved:
        for city_name in resolved:
            q = select(DeliveryRule).where(
                DeliveryRule.tenant_id == tenant_id,
                DeliveryRule.is_active.is_(True),
                DeliveryRule.city.ilike(f"%{_escape_like(city_name)}%"),
            )
            result = await db.execute(q)
            rules.extend(result.scalars().all())

    # Fallback: direct ILIKE search
    if not rules:
        q = select(DeliveryRule).where(
            DeliveryRule.tenant_id == tenant_id,
            DeliveryRule.is_active.is_(True),
            DeliveryRule.city.ilike(f"%{_escape_like(city)}%"),
        )
        result = await db.execute(q)
        rules = result.scalars().all()

    if not rules:
        # Return list of available cities for context
        all_q = select(DeliveryRule.city).where(
            DeliveryRule.tenant_id == tenant_id,
            DeliveryRule.is_active.is_(True),
        ).distinct()
        all_result = await db.execute(all_q)
        available = [r for r in all_result.scalars().all()]
        return {"found": False, "options": [], "available_cities": available}

    # Deduplicate
    seen = set()
    unique_rules = []
    for r in rules:
        if r.id not in seen:
            seen.add(r.id)
            unique_rules.append(r)

    return {
        "found": True,
        "options": [
            {
                "delivery_type": r.delivery_type,
                "city": r.city,
                "price": str(r.price),
                "currency": "UZS",
                "eta": f"{r.eta_min_days}-{r.eta_max_days} дней",
                "cod_available": r.cod_available,
            }
            for r in unique_rules
        ],
    }


async def create_lead(
    tenant_id: UUID,
    conversation_id: UUID,
    product_id: UUID | None,
    variant_id: UUID | None,
    db: AsyncSession,
) -> dict:
    """Create or update a lead from conversation (dedup by telegram_user_id + tenant_id)."""
    from src.conversations.models import Conversation

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        return {"error": "conversation_not_found"}

    tg_user_id = conversation.telegram_user_id

    # Dedup: find existing lead for this telegram user in this tenant
    existing_result = await db.execute(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.telegram_user_id == tg_user_id,
        ).order_by(Lead.created_at.desc()).limit(1)
    )
    existing_lead = existing_result.scalar_one_or_none()

    if existing_lead:
        # Update existing lead with latest data
        existing_lead.conversation_id = conversation_id
        tg_username = getattr(conversation, 'telegram_username', None)
        if tg_username:
            existing_lead.telegram_username = tg_username
        tg_name = getattr(conversation, 'telegram_first_name', None)
        if tg_name and not existing_lead.customer_name:
            existing_lead.customer_name = tg_name
        if product_id:
            existing_lead.interested_product_id = product_id
        if variant_id:
            existing_lead.interested_variant_id = variant_id
        await db.flush()
        return {"lead_id": str(existing_lead.id), "status": "updated"}

    lead = Lead(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        telegram_user_id=tg_user_id,
        telegram_username=getattr(conversation, 'telegram_username', None),
        customer_name=getattr(conversation, 'telegram_first_name', None),
        interested_product_id=product_id,
        interested_variant_id=variant_id,
        source="dm",
    )
    db.add(lead)
    await db.flush()
    return {"lead_id": str(lead.id), "status": "created"}


async def _reserve_inventory(tenant_id: UUID, variant_id: UUID, qty: int, db: AsyncSession) -> bool:
    """Reserve inventory for a variant. Uses FOR UPDATE to prevent oversell."""
    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.tenant_id == tenant_id,
            Inventory.variant_id == variant_id,
        ).with_for_update()
    )
    inv = inv_result.scalar_one_or_none()
    if not inv or inv.available_quantity < qty:
        return False
    inv.reserved_quantity += qty
    return True


async def _unreserve_inventory(tenant_id: UUID, variant_id: UUID, qty: int, db: AsyncSession) -> None:
    """Rollback a reservation."""
    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.tenant_id == tenant_id,
            Inventory.variant_id == variant_id,
        ).with_for_update()
    )
    inv = inv_result.scalar_one_or_none()
    if inv:
        inv.reserved_quantity = max(0, inv.reserved_quantity - qty)


async def create_order_draft(
    tenant_id: UUID,
    lead_id: UUID,
    variant_ids: list[UUID],
    quantities: list[int],
    customer_name: str,
    phone: str,
    city: str | None,
    address: str | None,
    db: AsyncSession,
    delivery_type: str | None = None,
) -> dict:
    """Create a draft order with one or more items. Reserves inventory."""
    from decimal import Decimal

    if not variant_ids:
        return {"error": "no variants specified"}

    items_info = []
    grand_total = Decimal("0")
    reserved_items: list[tuple[UUID, int]] = []  # Track for rollback

    for vid, qty in zip(variant_ids, quantities):
        var_result = await db.execute(
            select(ProductVariant).where(
                ProductVariant.id == vid,
                ProductVariant.tenant_id == tenant_id,
            )
        )
        variant = var_result.scalar_one_or_none()
        if not variant:
            # Rollback previous reservations
            for rv_id, rv_qty in reserved_items:
                await _unreserve_inventory(tenant_id, rv_id, rv_qty, db)
            return {"error": f"variant {vid} not found"}

        # Check & reserve inventory
        reserved = await _reserve_inventory(tenant_id, vid, qty, db)
        if not reserved:
            # Rollback previous reservations
            for rv_id, rv_qty in reserved_items:
                await _unreserve_inventory(tenant_id, rv_id, rv_qty, db)
            # Get actual stock for error message
            inv_r = await db.execute(
                select(Inventory).where(Inventory.tenant_id == tenant_id, Inventory.variant_id == vid)
            )
            inv_obj = inv_r.scalar_one_or_none()
            avail = inv_obj.available_quantity if inv_obj else 0
            return {"error": f"Недостаточно товара '{variant.title}' на складе. Доступно: {avail} шт."}
        reserved_items.append((vid, qty))

        item_total = variant.price * qty
        grand_total += item_total
        items_info.append({
            "variant": variant,
            "qty": qty,
            "unit_price": variant.price,
            "total_price": item_total,
        })

    # Add delivery cost if city provided
    delivery_cost = Decimal("0")
    delivery_eta = None
    delivery_note = None
    rule = None
    if city:
        resolved = _resolve_city(city)
        search_city = resolved[0] if resolved else city
        _del_query = select(DeliveryRule).where(
            DeliveryRule.tenant_id == tenant_id,
            DeliveryRule.is_active.is_(True),
            DeliveryRule.city.ilike(f"%{_escape_like(search_city)}%"),
        )
        if delivery_type:
            _del_query = _del_query.where(DeliveryRule.delivery_type == delivery_type)
        del_result = await db.execute(_del_query)
        rule = del_result.scalars().first()
        if rule:
            delivery_cost = rule.price
            delivery_eta = f"{rule.eta_min_days}-{rule.eta_max_days} дней"
            if delivery_cost > 0:
                delivery_note = f"доставка {delivery_cost} сум"
            else:
                delivery_note = "доставка включена"
        else:
            delivery_note = "стоимость доставки уточняется"

    grand_total += delivery_cost

    # Create order
    from src.orders.service import generate_order_number
    order_number = generate_order_number()
    order = Order(
        tenant_id=tenant_id,
        lead_id=lead_id,
        order_number=order_number,
        customer_name=customer_name,
        phone=phone,
        city=city,
        address=address,
        delivery_type=delivery_type or (rule.delivery_type if rule else None),
        total_amount=grand_total,
        currency="UZS",
        status="draft",
    )
    db.add(order)
    await db.flush()

    # Create order items
    order_items_out = []
    for info in items_info:
        oi = OrderItem(
            order_id=order.id,
            product_id=info["variant"].product_id,
            product_variant_id=info["variant"].id,
            qty=info["qty"],
            unit_price=info["unit_price"],
            total_price=info["total_price"],
        )
        db.add(oi)
        order_items_out.append({
            "title": info["variant"].title,
            "qty": info["qty"],
            "unit_price": str(info["unit_price"]),
            "total_price": str(info["total_price"]),
        })
    await db.flush()

    # Auto-update lead status to "converted"
    if lead_id:
        lead_result = await db.execute(
            select(Lead).where(Lead.id == lead_id)
        )
        lead_obj = lead_result.scalar_one_or_none()
        if lead_obj and lead_obj.status in ("new", "contacted", "qualified"):
            lead_obj.status = "converted"
            await db.flush()

    result = {
        "order_id": str(order.id),
        "order_number": order_number,
        "items": order_items_out,
        "delivery_cost": str(delivery_cost),
        "delivery_note": delivery_note or (f"доставка {delivery_cost} сум" if delivery_cost > 0 else "стоимость доставки уточняется"),
        "total_amount": str(grand_total),
        "currency": "UZS",
        "status": "draft",
    }
    if delivery_eta:
        result["delivery_eta"] = delivery_eta
    return result


async def add_item_to_order(
    tenant_id: UUID,
    conversation_id: UUID,
    order_number: str,
    variant_id: UUID,
    qty: int,
    db: AsyncSession,
) -> dict:
    """Add an item to an existing draft/confirmed order. Reserves inventory."""
    from src.conversations.models import Conversation
    from src.ai.policies import can_edit_order

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return {"error": "conversation_not_found"}

    order_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.order_number == _normalize_order_number(order_number),
        ).options(selectinload(Order.items))
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return {"success": False, "error": "Заказ с таким номером не найден"}

    # Verify ownership
    if order.lead_id:
        lead_result = await db.execute(select(Lead).where(Lead.id == order.lead_id))
        lead = lead_result.scalar_one_or_none()
        if lead and lead.telegram_user_id != conv.telegram_user_id:
            return {"success": False, "error": "Этот заказ не принадлежит вам"}

    # Check policy
    policy = can_edit_order(order.status)
    if not policy["allowed"]:
        return {"success": False, "error": policy["message"], "status": order.status}
    if policy["needs_operator"]:
        return {"success": False, "needs_operator": True, "message": policy["message"]}

    # Get variant info
    var_result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id,
            ProductVariant.tenant_id == tenant_id,
        )
    )
    variant = var_result.scalar_one_or_none()
    if not variant:
        return {"success": False, "error": "Товар не найден"}

    # Check if this variant is already in the order — BLOCK duplicate add
    for item in order.items:
        if item.product_variant_id == variant_id:
            return {
                "success": False,
                "error": f"'{variant.title}' уже есть в заказе ({item.qty} шт). Не добавляй повторно!",
                "already_in_order": True,
                "current_qty": item.qty,
            }

    # Reserve inventory for new item
    reserved = await _reserve_inventory(tenant_id, variant_id, qty, db)
    if not reserved:
        inv_r = await db.execute(
            select(Inventory).where(Inventory.tenant_id == tenant_id, Inventory.variant_id == variant_id)
        )
        inv_obj = inv_r.scalar_one_or_none()
        avail = inv_obj.available_quantity if inv_obj else 0
        return {"success": False, "error": f"Недостаточно товара '{variant.title}'. Доступно: {avail} шт."}

    # Add new order item
    item_total = variant.price * qty
    oi = OrderItem(
        order_id=order.id,
        product_id=variant.product_id,
        product_variant_id=variant.id,
        qty=qty,
        unit_price=variant.price,
        total_price=item_total,
    )
    db.add(oi)
    order.total_amount += item_total
    await db.flush()

    return {
        "success": True,
        "action": "item_added",
        "order_number": order.order_number,
        "item_title": variant.title,
        "item_price": str(variant.price),
        "qty": qty,
        "new_total": str(order.total_amount),
        "note": "Товар добавлен в СУЩЕСТВУЮЩИЙ заказ. НЕ спрашивай адрес/имя/телефон — заказ уже оформлен. Просто подтверди добавление.",
    }


async def remove_item_from_order(
    tenant_id: UUID,
    conversation_id: UUID,
    order_number: str,
    variant_id: UUID,
    qty: int | None,
    db: AsyncSession,
) -> dict:
    """Remove an item (or reduce qty) from an existing draft/confirmed order. Unreserves inventory."""
    from src.conversations.models import Conversation
    from src.ai.policies import can_edit_order

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return {"error": "conversation_not_found"}

    order_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.order_number == _normalize_order_number(order_number),
        ).options(selectinload(Order.items))
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return {"success": False, "error": "Заказ с таким номером не найден"}

    # Verify ownership
    if order.lead_id:
        lead_result = await db.execute(select(Lead).where(Lead.id == order.lead_id))
        lead = lead_result.scalar_one_or_none()
        if lead and lead.telegram_user_id != conv.telegram_user_id:
            return {"success": False, "error": "Этот заказ не принадлежит вам"}

    # Check policy
    policy = can_edit_order(order.status)
    if not policy["allowed"]:
        return {"success": False, "error": policy["message"], "status": order.status}
    if policy["needs_operator"]:
        return {"success": False, "needs_operator": True, "message": policy["message"]}

    # Find the item to remove
    removed_item = None
    for item in order.items:
        if item.product_variant_id == variant_id:
            removed_item = item
            break

    if not removed_item:
        return {"success": False, "error": "Этот товар не найден в заказе"}

    # Get title
    var_result = await db.execute(
        select(ProductVariant).where(ProductVariant.id == variant_id)
    )
    variant = var_result.scalar_one_or_none()
    removed_title = variant.title if variant else "товар"

    # Determine how many to remove
    remove_qty = qty if qty and qty < removed_item.qty else removed_item.qty

    if remove_qty < removed_item.qty:
        # Partial removal — reduce quantity
        removed_item.qty -= remove_qty
        removed_item.total_price = removed_item.unit_price * removed_item.qty
        await _unreserve_inventory(tenant_id, variant_id, remove_qty, db)
        order.total_amount -= removed_item.unit_price * remove_qty
        await db.flush()
        return {
            "success": True,
            "action": "quantity_reduced",
            "order_number": order.order_number,
            "item_title": removed_title,
            "removed_qty": remove_qty,
            "remaining_qty": removed_item.qty,
            "new_total": str(order.total_amount),
            "remaining_items": len(order.items),
            "note": "Количество уменьшено. НЕ спрашивай адрес — заказ уже оформлен.",
        }

    # Full removal — delete the item entirely
    # Can't remove the last item — suggest cancelling instead
    if len(order.items) <= 1:
        return {"success": False, "error": "Нельзя удалить единственный товар. Если хотите отменить заказ — используйте отмену."}

    await _unreserve_inventory(tenant_id, variant_id, removed_item.qty, db)
    order.total_amount -= removed_item.total_price
    await db.delete(removed_item)
    await db.flush()

    return {
        "success": True,
        "action": "item_removed",
        "order_number": order.order_number,
        "removed_item": removed_title,
        "new_total": str(order.total_amount),
        "remaining_items": len(order.items) - 1,
        "note": "Товар удалён из СУЩЕСТВУЮЩЕГО заказа. НЕ спрашивай адрес — заказ уже оформлен.",
    }


def _normalize_order_number(order_number: str) -> str:
    """Normalize order number — add ORD- prefix if missing."""
    num = order_number.strip().upper()
    if not num.startswith("ORD-"):
        num = f"ORD-{num}"
    return num


ORDER_STATUS_LABELS = {
    "draft": "Ожидает подтверждения",
    "confirmed": "Подтверждён",
    "processing": "В обработке",
    "shipped": "Отправлен",
    "delivered": "Доставлен",
    "cancelled": "Отменён",
}


async def cancel_order_by_number(
    tenant_id: UUID,
    conversation_id: UUID,
    order_number: str,
    db: AsyncSession,
    ai_settings=None,
) -> dict:
    """Cancel a draft order. Unreserves inventory. Only works for draft status."""
    from src.conversations.models import Conversation
    from src.ai.policies import can_cancel_order

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return {"error": "conversation_not_found"}

    order_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.order_number == _normalize_order_number(order_number),
        ).options(selectinload(Order.items))
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return {"cancelled": False, "error": "Заказ с таким номером не найден"}

    # Verify this order belongs to this user (through lead → telegram_user_id)
    if order.lead_id:
        lead_result = await db.execute(
            select(Lead).where(Lead.id == order.lead_id)
        )
        lead = lead_result.scalar_one_or_none()
        if lead and lead.telegram_user_id != conv.telegram_user_id:
            return {"cancelled": False, "error": "Этот заказ не принадлежит вам"}

    # Check policy (respects ai_settings if provided)
    policy = can_cancel_order(order.status, ai_settings)
    if not policy["allowed"]:
        return {
            "cancelled": False,
            "error": policy["message"],
            "status": order.status,
            "status_label": ORDER_STATUS_LABELS.get(order.status, order.status),
        }
    if policy["needs_operator"]:
        return {
            "cancelled": False,
            "needs_operator": True,
            "message": policy["message"],
            "order_number": order.order_number,
            "status": order.status,
        }

    # Cancel the order and unreserve inventory
    order.status = "cancelled"
    for item in order.items:
        if item.product_variant_id:
            await _unreserve_inventory(tenant_id, item.product_variant_id, item.qty, db)

    await db.flush()

    return {
        "cancelled": True,
        "order_number": order.order_number,
        "status": "cancelled",
        "status_label": "Отменён",
        "message": f"Заказ {order.order_number} отменён",
    }


async def check_order_status(
    tenant_id: UUID,
    conversation_id: UUID,
    order_number: str | None,
    db: AsyncSession,
) -> dict:
    """Check order status. If order_number provided, search by it. Otherwise find orders for this user."""
    from src.conversations.models import Conversation

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return {"error": "conversation_not_found"}

    if order_number:
        # Search by order number
        order_result = await db.execute(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.order_number == _normalize_order_number(order_number),
            ).options(selectinload(Order.items))
        )
        order = order_result.scalar_one_or_none()
        if not order:
            return {"found": False, "message": "Заказ с таким номером не найден. Проверьте номер."}

        # Verify ownership — don't leak other users' order info
        if order.lead_id:
            lead_result = await db.execute(select(Lead).where(Lead.id == order.lead_id))
            lead = lead_result.scalar_one_or_none()
            if lead and lead.telegram_user_id != conv.telegram_user_id:
                return {"found": False, "message": "Заказ с таким номером не найден. Проверьте номер."}

        # Build items list with variant info (batch-load variants)
        item_variant_ids = [item.product_variant_id for item in order.items if item.product_variant_id]
        variant_titles = {}
        if item_variant_ids:
            vr = await db.execute(
                select(ProductVariant.id, ProductVariant.title).where(ProductVariant.id.in_(item_variant_ids))
            )
            variant_titles = {vid: title for vid, title in vr.all()}

        items_info = []
        for item in order.items:
            items_info.append({
                "variant_id": str(item.product_variant_id) if item.product_variant_id else None,
                "title": variant_titles.get(item.product_variant_id, "?") if item.product_variant_id else "?",
                "qty": item.qty,
                "unit_price": str(item.unit_price),
                "total_price": str(item.total_price),
            })

        return {
            "found": True,
            "order_number": order.order_number,
            "status": order.status,
            "status_label": ORDER_STATUS_LABELS.get(order.status, order.status),
            "total_amount": str(order.total_amount),
            "city": order.city,
            "items": items_info,
            "created_at": order.created_at.strftime("%d.%m.%Y %H:%M"),
        }
    else:
        # Find orders by telegram_user_id through leads/conversations
        lead_result = await db.execute(
            select(Order).where(
                Order.tenant_id == tenant_id,
            ).join(
                Lead, Lead.id == Order.lead_id
            ).where(
                Lead.telegram_user_id == conv.telegram_user_id,
            ).order_by(Order.created_at.desc()).limit(5)
        )
        orders = lead_result.scalars().all()

        if not orders:
            return {"found": False, "message": "У вас пока нет заказов"}

        return {
            "found": True,
            "orders": [
                {
                    "order_number": o.order_number,
                    "status": o.status,
                    "status_label": ORDER_STATUS_LABELS.get(o.status, o.status),
                    "total_amount": str(o.total_amount),
                    "created_at": o.created_at.strftime("%d.%m.%Y"),
                }
                for o in orders
            ],
        }


async def get_customer_history(
    tenant_id: UUID,
    conversation_id: UUID,
    db: AsyncSession,
) -> dict:
    """Get returning customer's previous order data (name, phone, city, address).

    Used when customer says 'send to previous address' / 'олдинги адресс'.
    Returns the most recent order's delivery info so AI can confirm and reuse it.
    """
    from src.conversations.models import Conversation

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return {"found": False, "message": "conversation_not_found"}

    # Find previous orders by this user through leads
    order_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
        ).join(
            Lead, Lead.id == Order.lead_id
        ).where(
            Lead.telegram_user_id == conv.telegram_user_id,
        ).order_by(Order.created_at.desc()).limit(3)
    )
    orders = order_result.scalars().all()

    if not orders:
        return {"found": False, "message": "У клиента нет предыдущих заказов. Спроси имя, телефон и адрес."}

    # Return the most recent order's delivery info
    latest = orders[0]
    return {
        "found": True,
        "customer_name": latest.customer_name,
        "phone": latest.phone,
        "city": latest.city,
        "address": latest.address,
        "last_order_number": latest.order_number,
        "total_previous_orders": len(orders),
    }


async def request_return(
    tenant_id: UUID,
    conversation_id: UUID,
    order_number: str,
    reason: str,
    db: AsyncSession,
    ai_settings=None,
) -> dict:
    """Request a return/exchange for a delivered order.

    Checks policy (can_return_order) and creates a handoff if operator is required.
    """
    from src.conversations.models import Conversation
    from src.ai.policies import can_return_order

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return {"error": "conversation_not_found"}

    order_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.order_number == _normalize_order_number(order_number),
        ).options(selectinload(Order.items))
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return {"success": False, "error": "Заказ с таким номером не найден"}

    # Verify ownership through lead → telegram_user_id
    if order.lead_id:
        lead_result = await db.execute(select(Lead).where(Lead.id == order.lead_id))
        lead = lead_result.scalar_one_or_none()
        if lead and lead.telegram_user_id != conv.telegram_user_id:
            return {"success": False, "error": "Этот заказ не принадлежит вам"}

    # Check return policy (pass updated_at as delivery date proxy)
    policy = can_return_order(order.status, ai_settings, delivered_at=order.updated_at)
    if not policy["allowed"]:
        return {"success": False, "error": policy["message"], "status": order.status}

    if policy["needs_operator"]:
        # Create handoff for operator
        from src.handoffs.models import Handoff
        handoff = Handoff(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            reason=f"Возврат заказа {order.order_number}",
            priority="high",
            summary=f"Запрос на возврат: {order.order_number}. Причина: {reason}",
            linked_order_id=order.id,
        )
        db.add(handoff)
        await db.flush()
        return {
            "success": True,
            "needs_operator": True,
            "order_number": order.order_number,
            "message": policy["message"],
        }

    # Direct return (when require_operator_for_returns=False)
    order.status = "returned"
    await db.flush()
    return {
        "success": True,
        "order_number": order.order_number,
        "status": "returned",
        "status_label": "Возвращён",
        "message": f"Заказ {order.order_number} помечен на возврат",
    }
