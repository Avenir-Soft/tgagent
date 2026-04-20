"""Photo handling for AI orchestrator.

Extracts product images from tool results, picks correct variant photos
based on AI response context, force-fetches from DB, and cleans AI text.
"""

import logging
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Keywords indicating user wants to see photos
_PHOTO_KEYWORDS = {
    "фото", "фотк", "фотог", "фоточ", "покажи", "покажите", "photo", "picture",
    "pic", "image", "show me", "расм", "rasm", "сурат", "увидеть",
    "скинь", "скинуть", "скиньте", "скидывай", "отправь", "отправьте",
    "пришли", "пришлите", "картинк", "показать",
    # Uzbek: "show" / "send" / "photo"
    "курсат", "кўрсат", "курсатинг", "кўрсатинг", "ko'rsat", "ko'rsating",
    "korsat", "korsating", "юбор", "жўнат", "jo'nat", "jonat",
    "rasmini", "suratini", "suratni", "rasmni",
}

# Patterns to strip from AI text when photos are attached
_PHOTO_LIST_PATTERN = re.compile(
    r'(?:\n\s*\d+\.\s*(?:iPhone|Samsung|Apple|Sony|MacBook|iPad|AirPods|Anker|Xiaomi|Paltau|Chimgan|Bungee|Zipline|Tuzkon|Nefrit|Xiva)'
    r'\s[^\n]*(?:Photo|Фото|фото|rasm|surat)?\s*\d*\s*)+'
)
_PHOTO_LIST_DASH = re.compile(
    r'(?:\n\s*[-•]\s*(?:iPhone|Samsung|Apple|Sony|MacBook|iPad|AirPods|Anker|Xiaomi|Paltau|Chimgan|Bungee|Zipline|Tuzkon|Nefrit|Xiva)'
    r'\s[^\n]*(?:Photo|Фото|фото|rasm|surat)?\s*\d*\s*)+'
)
_PHOTO_HEADER = re.compile(r'[Вв]от\s+фото(?:графи[яи])?\s+(?:устройства|товара|тура)\s*:\s*\n?')
_PHOTO_DENY_PATTERNS = [
    re.compile(
        r'[Кк]\s*сожалени\w*[,.]?\s*(?:не удалось|не могу|нет возможности)'
        r'\s*(?:найти|показать|отправить|предоставить)\s*фотограф\w*[^.]*\.?\s*',
        re.IGNORECASE,
    ),
    re.compile(
        r'(?:[Нн]е удалось|[Нн]е могу)\s*(?:найти|показать|отправить|предоставить)'
        r'\s*фотограф\w*[^.]*\.?\s*',
        re.IGNORECASE,
    ),
    re.compile(r'[Нн]о\s+(?:они|у нас|я могу)\s', re.IGNORECASE),
    re.compile(r'I\s+(?:apologize|cannot|can\'t|am unable)[^.]*photo[^.]*\.?\s*', re.IGNORECASE),
]


# Cross-script color matching: English ↔ Cyrillic transliterations
_COLOR_TRANSLIT: dict[str, list[str]] = {
    "black": ["блэк", "чёрный", "черный", "қора", "qora"],
    "white": ["уайт", "белый", "оқ", "oq"],
    "natural": ["натурал", "натуральный", "табиий", "tabiiy"],
    "titanium": ["титаниум", "титан"],
    "blue": ["блю", "синий", "голубой", "кўк", "ko'k"],
    "gold": ["голд", "золотой", "олтин", "oltin"],
    "silver": ["силвер", "серебряный", "кумуш", "kumush"],
    "red": ["рэд", "красный", "қизил", "qizil"],
    "green": ["грин", "зелёный", "зеленый", "яшил", "yashil"],
    "purple": ["пёрпл", "фиолетовый", "бинафша", "binafsha"],
    "pink": ["пинк", "розовый", "пушти", "pushti"],
    "gray": ["грей", "серый", "кулранг", "kulrang"],
    "grey": ["грей", "серый", "кулранг", "kulrang"],
    "midnight": ["миднайт", "тунги"],
    "starlight": ["старлайт", "юлдузли"],
    "desert": ["дезерт", "саҳро"],
    "cream": ["крим", "крем", "кремовый"],
    "space": ["спейс"],
    "deep": ["дип"],
    "sierra": ["сиерра", "сиера"],
    "pacific": ["пасифик"],
    "graphite": ["графит"],
    "alpine": ["алпайн", "альпийский"],
    "coral": ["корал", "коралловый"],
    "phantom": ["фантом"],
    "pro": ["про"],
    "max": ["макс"],
    "ultra": ["ультра"],
}


def _color_matches_text(color_en: str, text: str) -> bool:
    """Check if English color name matches in multilingual text via transliteration."""
    if not color_en:
        return False
    text_lower = text.lower()
    color_lower = color_en.lower()

    # Direct match (exact substring)
    if color_lower in text_lower:
        return True

    # Check each word of the color name — ALL must match (direct or translit)
    words = color_lower.split()
    for word in words:
        if word in text_lower:
            continue  # direct match for this word
        translits = _COLOR_TRANSLIT.get(word, [])
        if any(t in text_lower for t in translits):
            continue  # translit match for this word
        return False  # this word doesn't match at all

    return True  # all words matched


def extract_images_from_tool_result(
    tool_name: str,
    result: dict,
    variant_images_map: dict,
    collected_image_urls: list[str],
) -> list[str]:
    """Extract image URLs from tool result, return updated collected_image_urls.

    Modifies result in-place (replaces image_url with flags to save tokens).
    Updates variant_images_map for get_variant_candidates.
    """
    if tool_name == "get_product_candidates":
        # Only mark photos as available — DON'T collect URLs here.
        # get_product_candidates returns multiple products (iPhones + Samsungs + etc.)
        # and collecting all their photos causes wrong images in album.
        # Photos are collected from get_variant_candidates (specific product) or force_fetch_photos.
        for prod in result.get("products", []):
            img = prod.pop("image_url", None)
            total_ph = prod.get("total_photos", 0)
            if img:
                prod["photo_available"] = True
                prod["total_photos"] = total_ph
            else:
                prod["total_photos"] = total_ph
        for prod in result.get("out_of_stock_products", []):
            prod.pop("image_url", None)

    elif tool_name == "get_variant_candidates":
        variant_images_map.clear()
        for vr in result.get("variants", []):
            v_imgs = vr.pop("image_urls", [])
            v_id = vr.get("variant_id", "")
            vr["photo_count"] = len(v_imgs)
            if v_imgs:
                variant_images_map[v_id] = {
                    "images": v_imgs,
                    "color": (vr.get("color") or "").lower(),
                    "title": (vr.get("title") or "").lower(),
                }

        # For single-variant products, attach directly
        if len(variant_images_map) == 1:
            collected_image_urls = list(list(variant_images_map.values())[0]["images"])
        elif variant_images_map:
            first_entry = next(iter(variant_images_map.values()))
            collected_image_urls = list(first_entry["images"])

        result["photos_attached"] = len(collected_image_urls)
        result["photos_note"] = "Photos are sent automatically as album. Do NOT list or number them in your reply."

    return collected_image_urls


def pick_variant_photos(
    variant_images_map: dict,
    final_text: str,
    user_message: str,
) -> list[str] | None:
    """Pick correct variant photos based on AI response + user message.

    Uses scoring: color match (direct/translit) scores highest,
    then unique title words. Picks the variant with the highest score.
    """
    if not variant_images_map or len(variant_images_map) <= 1 or not final_text:
        return None

    combined = (final_text or "").lower() + " " + user_message.lower()

    # Collect all colors to find UNIQUE distinguishing words
    all_colors = [vinfo["color"] for vinfo in variant_images_map.values() if vinfo["color"]]

    best_score = 0
    best_vid = None
    best_images = None

    for vid, vinfo in variant_images_map.items():
        score = 0
        vc = vinfo["color"]

        # --- Color match (strongest signal) ---
        if vc:
            # Full color string match (e.g. "natural titanium" in text)
            if vc in combined:
                score += 20
            elif _color_matches_text(vc, combined):
                # Cross-script match (e.g. "натурал титаниум" ↔ "natural titanium")
                score += 15

            # Match on UNIQUE color words only (words not shared by other variants)
            # e.g. "natural" is unique, "titanium" is shared → only score "natural"
            other_color_words: set[str] = set()
            for oc in all_colors:
                if oc != vc:
                    other_color_words.update(oc.split())
            for cw in vc.split():
                if cw in other_color_words:
                    continue  # shared word (e.g. "titanium") — skip
                if cw in combined:
                    score += 10
                else:
                    translits = _COLOR_TRANSLIT.get(cw, [])
                    if any(t in combined for t in translits):
                        score += 8

        if score > best_score:
            best_score = score
            best_vid = vid
            best_images = vinfo["images"]

    if best_images and best_score > 0:
        logger.info("PHOTO VARIANT MATCH: vid=%s score=%d", best_vid, best_score)
        return best_images

    return None


def user_wants_photos(user_message: str) -> bool:
    """Check if user explicitly asked to see photos."""
    return any(kw in user_message.lower() for kw in _PHOTO_KEYWORDS)


async def _pick_best_seller(tenant_id, candidates: list[dict], db: AsyncSession) -> str:
    """Pick the best-selling product from candidates by order_items count."""
    if len(candidates) == 1:
        return candidates[0]["product_id"]

    from sqlalchemy import select, func
    from src.orders.models import OrderItem
    from src.catalog.models import ProductVariant

    product_ids = [c["product_id"] for c in candidates]
    try:
        # Count order items per product (via variant → product mapping)
        result = await db.execute(
            select(ProductVariant.product_id, func.count(OrderItem.id).label("sales"))
            .join(OrderItem, OrderItem.variant_id == ProductVariant.id)
            .where(
                ProductVariant.product_id.in_(product_ids),
                ProductVariant.tenant_id == tenant_id,
            )
            .group_by(ProductVariant.product_id)
            .order_by(func.count(OrderItem.id).desc())
        )
        rows = result.all()
        if rows:
            best_pid = str(rows[0][0])
            best_name = next((c.get("name") for c in candidates if c["product_id"] == best_pid), "?")
            logger.info("PHOTO: best-seller pick: %s (%d sales)", best_name, rows[0][1])
            return best_pid
    except Exception as e:
        logger.debug("Best-seller query failed, using first result: %s", e)

    # No sales data — return first (most relevant by search ranking)
    return candidates[0]["product_id"]


async def force_fetch_photos(
    tenant_id, user_message: str, state_context: dict, db: AsyncSession,
) -> list[str]:
    """Force-fetch photos from DB when user asked but AI didn't provide.

    Returns list of image URLs (may be empty).
    """
    from src.ai.truth_tools import get_product_candidates, get_variant_candidates

    product_uuid = None

    # Strip photo-related words to get clean product search query
    # "скинь фотки айфона" → "айфона", "покажи фото iphone" → "iphone"
    clean_query = user_message.lower()
    for noise in ("скинь", "скинуть", "покажи", "показать", "пришли", "отправь", "кинь", "дай", "хочу", "можно",
                   "можете", "могу", "можешь", "отправить", "отправите",
                   "скиньте", "покажите", "присылайте", "присылать",
                   "фотки", "фоток", "фото", "фотографии", "фотку", "фоточки",
                   "фотографию", "фотографий", "картинки", "картинку", "фоточку",
                   "photo", "photos", "picture", "pictures", "pic", "pics",
                   "image", "images", "show", "send", "see", "want", "wanna",
                   "can", "give", "look", "loook", "okay", "ok",
                   "me", "it", "you", "please", "пж", "пожалуйста",
                   "у", "вас", "есть", "ваш", "ваши", "мне", "нам", "их", "а", "и", "на",
                   "the", "a", "an", "of", "for", "your", "their", "some", "any",
                   # Uzbek noise words
                   "курсат", "кўрсат", "курсатинг", "кўрсатинг", "юбор", "жўнат",
                   "ko'rsat", "ko'rsating", "korsat", "jonat", "jo'nat",
                   "расмини", "расмни", "суратини", "суратни",
                   "rasmini", "rasmni", "suratini", "suratni",
                   "салом", "salom", "керак", "kerak", "менга", "menga",
                   "бер", "берингиз", "ber", "bering", "beringiz"):
        clean_query = clean_query.replace(noise, "")
    clean_query = " ".join(clean_query.split()).strip()

    # Search with cleaned query (e.g. "айфона"), pick best-seller among matches
    if clean_query and len(clean_query) >= 2:
        try:
            search_result = await get_product_candidates(tenant_id, clean_query, db)
            if search_result.get("found") and search_result.get("products"):
                candidates = search_result["products"]
                product_uuid = await _pick_best_seller(tenant_id, candidates, db)
                logger.info("PHOTO: found product via cleaned search '%s': %s",
                            clean_query, product_uuid)
        except Exception as e:
            logger.debug("Product search for photo failed: %s", e)

    # Fallback: try full user message
    if not product_uuid:
        try:
            search_result = await get_product_candidates(tenant_id, user_message, db)
            if search_result.get("found") and search_result.get("products"):
                candidates = search_result["products"]
                product_uuid = await _pick_best_seller(tenant_id, candidates, db)
                logger.info("PHOTO: found product via full search: %s", product_uuid)
        except Exception as e:
            logger.debug("Product search for photo failed: %s", e)

    # Fallback: use last product from state_context that matches user message keywords
    if not product_uuid:
        products = state_context.get("products", {})
        msg_lower = user_message.lower()
        # First try: match product name against user message
        for pkey, pinfo in reversed(list(products.items())):
            pid = pinfo.get("product_id")
            if pid and any(w in msg_lower for w in pkey.lower().split() if len(w) > 3):
                product_uuid = pid
                logger.info("PHOTO: matched state_context product by name '%s'", pkey)
                break
        # Last resort: just take the last product
        if not product_uuid:
            for pkey, pinfo in reversed(list(products.items())):
                pid = pinfo.get("product_id")
                if pid:
                    product_uuid = pid
                    logger.info("PHOTO: fallback to last state_context product %s", pkey)
                    break

    if not product_uuid:
        logger.info("PHOTO: no product found to fetch photos for")
        return []

    try:
        photo_result = await get_variant_candidates(tenant_id, UUID(str(product_uuid)), db)
        best_imgs: list[str] = []
        msg_lower = user_message.lower()

        for vr in photo_result.get("variants", []):
            v_imgs = vr.get("image_urls", [])
            if not v_imgs:
                continue
            v_color = (vr.get("color") or "").lower()

            # Cross-script color match (e.g. "натурал титаниум" ↔ "natural titanium")
            if v_color and _color_matches_text(v_color, msg_lower):
                best_imgs = v_imgs
                logger.info("PHOTO FORCE-FETCH: matched color '%s'", v_color)
                break
            if not best_imgs:
                best_imgs = v_imgs  # fallback to first variant with images

        if best_imgs:
            logger.info("PHOTO FORCE-FETCH: got %d photos for %s", len(best_imgs), product_uuid)
        else:
            logger.info("PHOTO FORCE-FETCH: no images for %s", product_uuid)
        return best_imgs

    except Exception:
        logger.warning("Photo force-fetch failed", exc_info=True)
        return []


_FAKE_PHOTO_TEXT = re.compile(
    r'\n?\s*(?:📸\s*)?(?:\[?[Ff]otosuratlar\]?|Фотосуратлар|фотографии|photos?)\s*'
    r'(?:yuboriladi|yuborilmoqda|quyida|ниже|below|отправлю|отправляю)?'
    r'[:.!]?\s*(?:\n|$)',
    re.IGNORECASE | re.MULTILINE,
)
# Catch "Mana tur suratlari:", "Mana tafsilotlar:", "Вот фото тура:", "Mana fotosuratlar:" standalone lines
_FAKE_PHOTO_LINE = re.compile(
    r'\n?\s*(?:Mana\s+(?:tur\s+)?(?:suratlari|fotosuratlar|tafsilotlar)|Вот\s+фото(?:графии)?\s+тура)\s*[:.!]?\s*(?:\n|$)',
    re.IGNORECASE | re.MULTILINE,
)


def clean_photo_text(final_text: str, has_photos: bool) -> str:
    """Clean AI text that contradicts photo sending or lists individual photos.

    Always strips fake photo promises. Deep cleaning only when photos are attached.
    """
    if not final_text:
        return final_text

    # Always strip fake "photos will be sent" text (longer patterns first)
    cleaned = _FAKE_PHOTO_LINE.sub('', final_text)
    cleaned = _FAKE_PHOTO_TEXT.sub('', cleaned).strip()

    if not has_photos:
        return cleaned

    # Deep clean when photos are attached (keep fake-text stripping from above)
    cleaned = _PHOTO_LIST_PATTERN.sub('', cleaned)
    cleaned = _PHOTO_LIST_DASH.sub('', cleaned)
    cleaned = _PHOTO_HEADER.sub('', cleaned)

    for pat in _PHOTO_DENY_PATTERNS:
        cleaned = pat.sub('', cleaned)

    cleaned = cleaned.strip()
    if cleaned and len(cleaned) > 5:
        return cleaned
    return "Mana tur suratlari:"
