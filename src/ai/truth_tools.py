"""Truth tools layer — deterministic data access for AI agent.

These are NOT LLM calls. They return factual data from the database.
The AI agent calls these tools to get tours, prices, seats, bookings, etc.

Adapted for Easy Tour / Oson Turizm — tour agency.
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

from src.catalog.models import Category, Inventory, Product, ProductAlias, ProductMedia, ProductVariant
from src.leads.models import Lead
from src.orders.models import Order, OrderItem

_logger = logging.getLogger(__name__)

# ── Cache layer ───────────────────────────────────────────────────────────────
_cat_cache: dict[str, tuple[dict, float]] = {}
_CAT_TTL = 300

_SEARCH_TTL = 180
_redis_cache = None


async def _get_cache_redis():
    global _redis_cache
    if _redis_cache is None:
        import redis.asyncio as aioredis
        from src.core.config import settings as cfg
        _redis_cache = aioredis.from_url(cfg.redis_url, decode_responses=True)
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
    # Don't cache "not found" results — prevents stale negatives
    if not result.get("found", True):
        return
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


# ── Tour category aliases ────────────────────────────────────────────────────
CATEGORY_NAME_ALIASES: dict[str, list[str]] = {
    "Yengil yurish": [
        "yengil", "oson", "sharshara", "waterfall", "ko'l", "lake",
        "водопад", "озеро", "лёгкий", "легкий", "прогулка",
        "шаршара", "енгил", "осон",
        "light", "easy", "hiking", "yurish",
    ],
    "O'rta yurish": [
        "o'rta", "tog'", "tog' yurish", "mountain", "hiking",
        "средний", "горы", "горный",
        "medium", "moderate",
    ],
    "Adrenalin": [
        "adrenalin", "bungee", "banji", "zipline", "extreme", "sakrash",
        "адреналин", "банджи", "экстрим", "прыжок",
        "adventure", "extreme",
    ],
    "4x4 tur": [
        "4x4", "jeep", "offroad", "jip", "off-road",
        "джип", "внедорожник", "оффроад",
    ],
    "Kemping": [
        "kemping", "camping", "chodir", "lager", "camp",
        "кемпинг", "палатка", "лагерь",
    ],
    "Ko'p kunlik": [
        "ko'p kunlik", "multi-day", "xiva", "khiva", "samarqand",
        "многодневный", "хива", "самарканд",
        "multi", "several days",
    ],
    "Tadbirlar": [
        "tadbir", "event", "party", "kontsert", "festival", "bayram",
        "мероприятие", "вечеринка", "концерт", "фестиваль",
    ],
    "Xalqaro": [
        "xalqaro", "international", "qirg'iziston", "kyrgyzstan",
        "международный", "кыргызстан", "заграница",
        "чет эл", "чет давлат", "хорижий", "хориж",
        "abroad", "foreign",
    ],
}


TOUR_TYPE_KEYWORDS: dict[str, list[str]] = {
    "waterfall": ["sharshara", "водопад", "paltau", "chukuraksu", "ispay", "tovoqsoy"],
    "mountain": ["tog'", "chimgan", "oqtosh", "горы", "mountain", "hiking"],
    "adrenaline": ["bungee", "banji", "zipline", "kayak", "sakrash", "прыжок"],
    "offroad": ["4x4", "nefrit", "jeep", "jip", "offroad", "внедорожник"],
    "camping": ["kemping", "camping", "tuzkon", "chodir", "палатка", "кемпинг"],
    "cultural": ["xiva", "samarqand", "buxoro", "хива", "самарканд", "бухара"],
    "event": ["party", "mewa", "kontsert", "festival", "вечеринка", "концерт"],
    "international": ["qirg'iziston", "kyrgyzstan", "кыргызстан", "thailand"],
}


# ── Cyrillic ↔ Latin transliteration (Uzbek) ────────────────────────────────
_CYR_TO_LAT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "'", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}
_LAT_TO_CYR: dict[str, str] = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е",
    "j": "ж", "z": "з", "i": "и", "y": "й", "k": "к", "l": "л", "m": "м",
    "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "t": "т", "u": "у",
    "f": "ф", "x": "х", "q": "қ", "h": "ҳ",
}
# Multi-char Latin → Cyrillic (order matters: longer first)
_LAT_DIGRAPHS_TO_CYR: list[tuple[str, str]] = [
    ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ye", "е"),
    ("sh", "ш"), ("ch", "ч"), ("ts", "ц"), ("g'", "ғ"), ("o'", "ў"),
]


def _transliterate_cyr_to_lat(text: str) -> str:
    """Convert Uzbek Cyrillic text to Latin."""
    result = []
    for ch in text:
        lower = ch.lower()
        if lower in _CYR_TO_LAT:
            mapped = _CYR_TO_LAT[lower]
            if ch.isupper() and mapped:
                mapped = mapped[0].upper() + mapped[1:]  # Only capitalize first char
            result.append(mapped)
        else:
            result.append(ch)
    return "".join(result)


def _transliterate_lat_to_cyr(text: str) -> str:
    """Convert Uzbek Latin text to Cyrillic."""
    result = []
    i = 0
    lower_text = text.lower()
    while i < len(text):
        matched = False
        # Check digraphs first (2+ chars)
        for lat, cyr in _LAT_DIGRAPHS_TO_CYR:
            if lower_text[i:i+len(lat)] == lat:
                result.append(cyr.upper() if text[i].isupper() else cyr)
                i += len(lat)
                matched = True
                break
        if not matched:
            ch = text[i]
            lower = ch.lower()
            if lower in _LAT_TO_CYR:
                mapped = _LAT_TO_CYR[lower]
                result.append(mapped.upper() if ch.isupper() else mapped)
            else:
                result.append(ch)
            i += 1
    return "".join(result)


def _has_cyrillic(text: str) -> bool:
    return any("\u0400" <= ch <= "\u04ff" for ch in text)


def _has_latin(text: str) -> bool:
    return any("a" <= ch.lower() <= "z" for ch in text)


# ── Category name Cyrillic mapping ───────────────────────────────────────────
_CATEGORY_CYR: dict[str, str] = {
    "Yengil yurish": "Енгил юриш",
    "O'rta yurish": "Ўрта юриш",
    "Adrenalin": "Адреналин",
    "4x4 tur": "4x4 тур",
    "Kemping": "Кемпинг",
    "Ko'p kunlik": "Кўп кунлик",
    "Tadbirlar": "Тадбирлар",
    "Xalqaro": "Халқаро",
}

# Common Latin words → Cyrillic (for data from DB)
_WORD_CYR: dict[str, str] = {
    "so'm": "сўм", "aprel": "апрел", "may": "май", "iyun": "июн",
    "iyul": "июл", "avgust": "август", "metro": "метро",
    "Transport": "Транспорт", "transport": "транспорт",
    "guide": "гид", "piknik": "пикник", "tushlik": "тушлик",
    "Chorsu": "Чорсу", "Xitoy": "Хитой",
}


def _transliterate_value(text: str) -> str:
    """Transliterate a single string value, preserving numbers and punctuation."""
    if not text or not _has_latin(text):
        return text
    # Replace known words first
    result = text
    for lat, cyr in _WORD_CYR.items():
        result = result.replace(lat, cyr)
    # Transliterate remaining Latin segments
    parts = []
    i = 0
    while i < len(result):
        if "a" <= result[i].lower() <= "z":
            # Collect Latin segment
            seg_start = i
            while i < len(result) and ("a" <= result[i].lower() <= "z" or result[i] in "'ʻʼ"):
                i += 1
            seg = result[seg_start:i]
            parts.append(_transliterate_lat_to_cyr(seg))
        else:
            parts.append(result[i])
            i += 1
    return "".join(parts)


_TOUR_DETAIL_TRANSLATIONS = {
    # included items
    "Transport": "Транспорт", "transport": "транспорт",
    "chodir": "палатка", "Chodir": "Палатка",
    "uyqu qopi": "спальник", "Uyqu qopi": "Спальник",
    "kechki ovqat": "ужин", "Kechki ovqat": "Ужин",
    "nonushta": "завтрак", "Nonushta": "Завтрак",
    "tushlik": "обед", "Tushlik": "Обед",
    "guide": "гид", "Guide": "Гид", "gid": "гид", "Gid": "Гид",
    "sug'urta": "страховка", "Sug'urta": "Страховка",
    # what_to_bring
    "Issiq kiyim": "Тёплая одежда", "issiq kiyim": "тёплая одежда",
    "fonar": "фонарик", "Fonar": "Фонарик",
    "shaxsiy buyumlar": "личные вещи", "Shaxsiy buyumlar": "Личные вещи",
    "Trek oyoq kiyim": "Треккинговая обувь", "trek oyoq kiyim": "треккинговая обувь",
    "ryukzak": "рюкзак", "Ryukzak": "Рюкзак",
    "suv 2L": "вода 2Л", "Suv 2L": "Вода 2Л", "suv": "вода",
    "snack": "перекус", "Snack": "Перекус",
    # meeting points
    "Chorsu metro": "метро Чорсу", "chorsu metro": "метро Чорсу",
    "Oybek metro": "метро Ойбек", "oybek metro": "метро Ойбек",
}


def _translate_tour_details(details: dict) -> dict:
    """Translate Uzbek Latin tour details to Russian for multilingual display."""
    translated = {}
    for key, value in details.items():
        if isinstance(value, str):
            result = value
            # Sort by length desc to replace longer patterns first
            for uz, ru in sorted(_TOUR_DETAIL_TRANSLATIONS.items(), key=lambda x: -len(x[0])):
                result = result.replace(uz, ru)
            translated[key] = result
        else:
            translated[key] = value
    return translated


def transliterate_tool_result(data, to_script: str = "cyrillic"):
    """Recursively transliterate all string values in a tool result dict/list.

    Used when detected_lang is 'uz_cyrillic' to convert Latin DB data to Cyrillic.
    Skips keys that should stay Latin (IDs, URLs, currencies, etc.).
    """
    if to_script != "cyrillic":
        return data

    _SKIP_KEYS = {"product_id", "variant_id", "order_id", "category_id",
                  "image_url", "currency", "error", "_handoff_hint", "order_number"}

    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if k in _SKIP_KEYS:
                result[k] = v
            elif k == "name" and isinstance(v, str):
                # Category/tour names — use static mapping first
                result[k] = _CATEGORY_CYR.get(v, _transliterate_value(v))
            elif isinstance(v, str):
                result[k] = _transliterate_value(v)
            elif isinstance(v, (dict, list)):
                result[k] = transliterate_tool_result(v, to_script)
            else:
                result[k] = v
        return result
    elif isinstance(data, list):
        return [transliterate_tool_result(item, to_script) for item in data]
    elif isinstance(data, str):
        return _transliterate_value(data)
    return data


def _classify_tour_type(name: str, description: str, category: str) -> str:
    """Classify tour into a specific type based on name/description keywords."""
    combined = f"{name} {description}".lower()
    for ttype, keywords in TOUR_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return ttype
    return category.lower() if category else "other"


async def list_categories(tenant_id: UUID, db: AsyncSession) -> dict:
    """List all active tour categories with tour counts (cached 5 min)."""
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
            entry = {
                "name": cat.name,
                "tour_count": count,
            }
            if cat.name_ru:
                entry["name_ru"] = cat.name_ru
            if cat.name_uz_cyr:
                entry["name_uz_cyr"] = cat.name_uz_cyr
            if cat.name_en:
                entry["name_en"] = cat.name_en
            cat_list.append(entry)

    data = {
        "categories": cat_list,
        "total_categories": len(cat_list),
        "_display_rule": "IMPORTANT: Show name_ru for Russian users, name_uz_cyr for Cyrillic users, name_en for English users. NEVER show raw 'name' to non-Uzbek-Latin users.",
    }
    _cat_cache[key] = (data, _time.monotonic())
    return data


async def get_product_candidates(tenant_id: UUID, query: str, db: AsyncSession) -> dict:
    """Search tours by ILIKE on name, alias, variant title, category, brand (difficulty), model (duration).

    Returns up to 15 matching tours ranked by relevance.
    """
    search_terms = [query.strip()]
    words = query.strip().split()
    if len(words) > 1:
        search_terms.extend([w for w in words if len(w) >= 2])

    # Add stemmed forms for Russian + Uzbek plurals/cases
    _ru_suffixes = ("ы", "и", "ов", "ей", "ами", "ях", "ам", "у", "е", "ой", "ом")
    _uz_suffixes = ("lar", "larni", "larning", "larda", "lardan", "larga",
                     "ni", "ning", "da", "dan", "ga", "dagi", "ini", "ining")
    _uz_cyr_suffixes = ("лар", "ларни", "ларнинг", "ларда", "лардан", "ларга",
                         "ни", "нинг", "да", "дан", "га", "даги", "ини", "ининг")
    stemmed = []
    for w in search_terms:
        wl = w.lower().rstrip("?!.,;:")
        if len(wl) >= 4:
            # Uzbek Latin suffixes first (longer)
            for suf in sorted(_uz_suffixes, key=len, reverse=True):
                if wl.endswith(suf) and len(wl) - len(suf) >= 3:
                    stemmed.append(wl[: -len(suf)])
                    break
            # Uzbek Cyrillic suffixes
            for suf in sorted(_uz_cyr_suffixes, key=len, reverse=True):
                if wl.endswith(suf) and len(wl) - len(suf) >= 2:
                    stemmed.append(wl[: -len(suf)])
                    break
            # Russian suffixes
            for suf in sorted(_ru_suffixes, key=len, reverse=True):
                if wl.endswith(suf) and len(wl) - len(suf) >= 3:
                    stemmed.append(wl[: -len(suf)])
                    break
    search_terms.extend(stemmed)

    # ── Transliterate Cyrillic ↔ Latin to find tours regardless of script ──
    transliterated = []
    for t in search_terms:
        if _has_cyrillic(t):
            transliterated.append(_transliterate_cyr_to_lat(t))
        elif _has_latin(t):
            transliterated.append(_transliterate_lat_to_cyr(t))
    search_terms.extend(transliterated)

    # Normalize apostrophes: "Qirg'iziston" → also search "Qirgiziston"
    for t in list(search_terms):
        if "'" in t or "\u2018" in t or "\u2019" in t:
            clean = t.replace("'", "").replace("\u2018", "").replace("\u2019", "")
            search_terms.append(clean)

    # Resolve category aliases
    q_lower = query.strip().lower()
    for db_name, aliases in CATEGORY_NAME_ALIASES.items():
        if q_lower in aliases or any(q_lower in a or a in q_lower for a in aliases):
            search_terms.append(db_name)

    # Check Redis cache
    cached_result = await _search_cache_get(tenant_id, query)
    if cached_result is not None:
        return cached_result

    # Build subqueries for all terms — single DB round-trip
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
        total_seats = 0
        prices = []
        for v in active_variants:
            for inv in (v.inventory or []):
                avail = max(0, (inv.quantity or 0) - (inv.reserved_quantity or 0))
                total_seats += avail
            if v.price:
                prices.append(float(v.price))

        media_sorted = sorted((p.media or []), key=lambda m: m.sort_order)
        image_url = media_sorted[0].url if media_sorted else None

        _all_photo_urls = set()
        for m in media_sorted:
            if m.url:
                _all_photo_urls.add(m.url)
        for v in active_variants:
            for m in (v.media or []):
                if m.url:
                    _all_photo_urls.add(m.url)

        # Build name with translations
        _entry: dict = {
            "product_id": str(p.id),
            "name": p.name,
        }
        if p.name_ru:
            _entry["name_ru"] = p.name_ru
        if p.name_en:
            _entry["name_en"] = p.name_en
        if p.name_uz_cyr:
            _entry["name_uz_cyr"] = p.name_uz_cyr
        # Category with translations
        _cat_name = p.category.name if p.category else None
        if p.category:
            if p.category.name_ru:
                _entry["category_ru"] = p.category.name_ru
        _entry.update({
            "difficulty": p.brand,  # brand field repurposed as difficulty
            "duration": p.model,    # model field repurposed as duration
            "category": _cat_name,
            "tour_type": _classify_tour_type(p.name, p.description or "", p.category.name if p.category else ""),
            "departure_dates_count": len(active_variants),
            "price_range": f"{min(prices):.0f}–{max(prices):.0f}" if prices else None,
            "currency": active_variants[0].currency if active_variants and active_variants[0].currency else "UZS",
            "in_stock": total_seats > 0,
            "total_seats_available": total_seats,
            "image_url": image_url,
            "total_photos": len(_all_photo_urls),
        })
        product_list.append(_entry)

    # Rank by relevance
    q_lower = query.strip().lower()
    def _relevance(p):
        name_l = (p["name"] or "").lower()
        if name_l == q_lower:
            return 0
        if q_lower in name_l or name_l in q_lower:
            return 1
        return 3

    product_list.sort(key=_relevance)

    in_stock = [p for p in product_list if p["in_stock"]]
    out_of_stock = [p for p in product_list if not p["in_stock"]]

    result_data = {
        "found": len(in_stock) > 0 or len(out_of_stock) > 0,
        "products": in_stock,
        "_display_rule": "Use name_ru for Russian users, name_en for English, name_uz_cyr for Cyrillic. Translate difficulty/duration values to user's language.",
    }
    if out_of_stock:
        result_data["sold_out_tours"] = out_of_stock
        result_data["suggestion"] = "Bu turlar mavjud lekin joylar tugagan. Boshqa sanalar yoki turlar taklif qiling."

    await _search_cache_set(tenant_id, query, result_data)
    return result_data


async def get_variant_candidates(tenant_id: UUID, product_id: UUID, db: AsyncSession) -> dict:
    """List active departure dates for a tour with date, time, price, available seats, and details."""
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

    prod_result = await db.execute(
        select(Product)
        .where(Product.id == product_id, Product.tenant_id == tenant_id)
        .options(selectinload(Product.media))
    )
    product = prod_result.scalar_one_or_none()
    product_media = sorted((product.media or []) if product else [], key=lambda m: m.sort_order)

    # Batch-load inventories
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
        available_seats = inv.available_quantity if inv else 0
        total_seats = inv.quantity if inv else 0

        variant_media = sorted((v.media or []), key=lambda m: m.sort_order)
        variant_image_urls = [m.url for m in variant_media if m.url]
        if not variant_image_urls:
            variant_image_urls = product_image_urls

        entry = {
            "variant_id": str(v.id),
            "title": v.title,
            "departure_date": v.color,      # color field repurposed as departure_date
            "departure_time": v.storage,     # storage field repurposed as departure_time
            "price": str(v.price),
            "currency": v.currency,
            "available_seats": available_seats,
            "total_seats": total_seats,
            "in_stock": available_seats > 0,
            "image_urls": variant_image_urls,
            "photo_count": len(variant_image_urls),
        }
        # Include tour details — always provide both original and translated
        if v.attributes_json:
            entry["details"] = _translate_tour_details(v.attributes_json)
            entry["details_original"] = v.attributes_json
        variant_list.append(entry)

    return {"found": True, "variants": variant_list}


async def get_variant_price(tenant_id: UUID, variant_id: UUID, db: AsyncSession) -> dict:
    """Get exact price for a specific tour date."""
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
    """Get available seats for a specific tour date."""
    result = await db.execute(
        select(Inventory).where(
            Inventory.tenant_id == tenant_id,
            Inventory.variant_id == variant_id,
        )
    )
    inv = result.scalar_one_or_none()

    if not inv:
        return {"found": False, "in_stock": False, "available_seats": 0}

    return {
        "found": True,
        "variant_id": str(variant_id),
        "in_stock": inv.available_quantity > 0,
        "available_seats": inv.available_quantity,
        "total_seats": inv.quantity,
    }


# ── Lead management ─────────────────────────────────────────────────────────

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

    existing_result = await db.execute(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.telegram_user_id == tg_user_id,
        ).order_by(Lead.created_at.desc()).limit(1)
    )
    existing_lead = existing_result.scalar_one_or_none()

    if existing_lead:
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


# ── Inventory reservation ────────────────────────────────────────────────────

async def _reserve_inventory(tenant_id: UUID, variant_id: UUID, qty: int, db: AsyncSession) -> bool:
    """Reserve seats for a tour date. Uses FOR UPDATE to prevent overbooking."""
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
    """Rollback a seat reservation."""
    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.tenant_id == tenant_id,
            Inventory.variant_id == variant_id,
        ).with_for_update()
    )
    inv = inv_result.scalar_one_or_none()
    if inv:
        inv.reserved_quantity = max(0, inv.reserved_quantity - qty)


# ── Booking (order) creation ─────────────────────────────────────────────────

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
    """Create a tour booking with one item (tour date + num participants). Reserves seats."""
    import secrets

    if not variant_ids:
        return {"error": "no variants specified"}

    items_info = []
    grand_total = Decimal("0")
    reserved_items: list[tuple[UUID, int]] = []

    for vid, qty in zip(variant_ids, quantities):
        var_result = await db.execute(
            select(ProductVariant).where(
                ProductVariant.id == vid,
                ProductVariant.tenant_id == tenant_id,
            )
        )
        variant = var_result.scalar_one_or_none()
        if not variant:
            for rv_id, rv_qty in reserved_items:
                await _unreserve_inventory(tenant_id, rv_id, rv_qty, db)
            return {"error": f"variant {vid} not found"}

        # Check & reserve seats
        reserved = await _reserve_inventory(tenant_id, vid, qty, db)
        if not reserved:
            for rv_id, rv_qty in reserved_items:
                await _unreserve_inventory(tenant_id, rv_id, rv_qty, db)
            inv_r = await db.execute(
                select(Inventory).where(Inventory.tenant_id == tenant_id, Inventory.variant_id == vid)
            )
            inv_obj = inv_r.scalar_one_or_none()
            avail = inv_obj.available_quantity if inv_obj else 0
            return {"error": f"Bu sanaga joylar yetarli emas. Bo'sh joylar: {avail} ta"}
        reserved_items.append((vid, qty))

        item_total = variant.price * qty
        grand_total += item_total
        items_info.append({
            "variant": variant,
            "qty": qty,
            "unit_price": variant.price,
            "total_price": item_total,
        })

    # Create booking (no delivery for tours)
    order_number = f"BK-{secrets.token_hex(4).upper()}"
    order = Order(
        tenant_id=tenant_id,
        lead_id=lead_id,
        order_number=order_number,
        customer_name=customer_name,
        phone=phone,
        total_amount=grand_total,
        currency="UZS",
        status="pending_payment",
    )
    db.add(order)
    await db.flush()

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

    # Auto-update lead status
    if lead_id:
        lead_result = await db.execute(
            select(Lead).where(Lead.id == lead_id)
        )
        lead_obj = lead_result.scalar_one_or_none()
        if lead_obj and lead_obj.status in ("new", "contacted", "qualified"):
            lead_obj.status = "converted"
            await db.flush()

    return {
        "order_id": str(order.id),
        "order_number": order_number,
        "items": order_items_out,
        "total_amount": str(grand_total),
        "currency": "UZS",
        "status": "pending_payment",
        "payment_note": "To'lovni amalga oshirib, chek rasmini yuboring 📸 (Payme, Click yoki naqd)",
    }


# ── Order number normalization ───────────────────────────────────────────────

def _normalize_order_number(order_number: str) -> str:
    """Normalize booking number — add BK- prefix if missing."""
    num = order_number.strip().upper()
    if not num.startswith("BK-"):
        # Also accept legacy ORD- prefix
        if num.startswith("ORD-"):
            return num
        num = f"BK-{num}"
    return num


# ── Booking status labels ────────────────────────────────────────────────────

# Default status labels (Uzbek Latin) — used when language is not specified
ORDER_STATUS_LABELS = {
    "draft": "Qoralama",
    "pending_payment": "To'lov kutilmoqda",
    "confirmed": "Tasdiqlangan",
    "completed": "Yakunlangan",
    "cancelled": "Bekor qilindi",
}

# These are returned to LLM in tool results — LLM translates based on system prompt language directive


async def cancel_order_by_number(
    tenant_id: UUID,
    conversation_id: UUID,
    order_number: str,
    db: AsyncSession,
    ai_settings=None,
) -> dict:
    """Cancel a booking. Unreserves seats. Works for draft/pending_payment."""
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
        return {"cancelled": False, "error": "Buyurtma topilmadi"}

    if order.lead_id:
        lead_result = await db.execute(
            select(Lead).where(Lead.id == order.lead_id)
        )
        lead = lead_result.scalar_one_or_none()
        if lead and lead.telegram_user_id != conv.telegram_user_id:
            return {"cancelled": False, "error": "Bu buyurtma sizga tegishli emas"}

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

    order.status = "cancelled"
    for item in order.items:
        if item.product_variant_id:
            await _unreserve_inventory(tenant_id, item.product_variant_id, item.qty, db)

    await db.flush()

    return {
        "cancelled": True,
        "order_number": order.order_number,
        "status": "cancelled",
        "status_label": "Bekor qilindi",
        "message": f"Buyurtma {order.order_number} bekor qilindi",
    }


async def check_order_status(
    tenant_id: UUID,
    conversation_id: UUID,
    order_number: str | None,
    db: AsyncSession,
    state_context: dict | None = None,
) -> dict:
    """Check booking status."""
    from src.conversations.models import Conversation

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return {"error": "conversation_not_found"}

    if order_number:
        order_result = await db.execute(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.order_number == _normalize_order_number(order_number),
            ).options(selectinload(Order.items))
        )
        order = order_result.scalar_one_or_none()
        if not order:
            return {"found": False, "message": "Buyurtma topilmadi. Raqamni tekshiring."}

        if order.lead_id:
            lead_result = await db.execute(select(Lead).where(Lead.id == order.lead_id))
            lead = lead_result.scalar_one_or_none()
            if lead and lead.telegram_user_id != conv.telegram_user_id:
                return {"found": False, "message": "Buyurtma topilmadi. Raqamni tekshiring."}

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
                "participants": item.qty,
                "unit_price": str(item.unit_price),
                "total_price": str(item.total_price),
            })

        return {
            "found": True,
            "order_number": order.order_number,
            "status": order.status,
            "status_label": ORDER_STATUS_LABELS.get(order.status, order.status),
            "total_amount": str(order.total_amount),
            "items": items_info,
            "created_at": order.created_at.strftime("%d.%m.%Y %H:%M"),
        }
    else:
        # Use outerjoin to handle orders with NULL lead_id
        lead_result = await db.execute(
            select(Order).where(
                Order.tenant_id == tenant_id,
            ).outerjoin(
                Lead, Lead.id == Order.lead_id
            ).where(
                Lead.telegram_user_id == conv.telegram_user_id,
            ).order_by(Order.created_at.desc()).limit(5)
        )
        orders = list(lead_result.scalars().all())

        # Fallback: also find orders from state_context (covers NULL lead_id)
        if state_context:
            ctx_order_nums = [o.get("order_number") for o in state_context.get("orders", []) if o.get("order_number")]
            if ctx_order_nums:
                existing_nums = {o.order_number for o in orders}
                missing_nums = [n for n in ctx_order_nums if n not in existing_nums]
                if missing_nums:
                    extra_result = await db.execute(
                        select(Order).where(
                            Order.tenant_id == tenant_id,
                            Order.order_number.in_(missing_nums),
                        ).options(selectinload(Order.items))
                    )
                    orders.extend(extra_result.scalars().all())

        if not orders:
            return {"found": False, "message": "Sizda hali buyurtmalar yo'q"}

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
    """Get returning customer's previous booking info (name, phone)."""
    from src.conversations.models import Conversation

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return {"found": False, "message": "conversation_not_found"}

    order_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
        ).outerjoin(
            Lead, Lead.id == Order.lead_id
        ).where(
            Lead.telegram_user_id == conv.telegram_user_id,
        ).order_by(Order.created_at.desc()).limit(3)
    )
    orders = order_result.scalars().all()

    if not orders:
        return {"found": False, "message": "Mijozning oldingi buyurtmalari yo'q. Ism va telefon so'rang."}

    latest = orders[0]
    return {
        "found": True,
        "customer_name": latest.customer_name,
        "phone": latest.phone,
        "last_order_number": latest.order_number,
        "total_previous_orders": len(orders),
    }
