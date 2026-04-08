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
    "фото", "фотк", "фотог", "фоточ", "покажи", "photo", "picture",
    "pic", "image", "show me", "расм", "rasm", "сурат", "увидеть",
}

# Patterns to strip from AI text when photos are attached
_PHOTO_LIST_PATTERN = re.compile(
    r'(?:\n\s*\d+\.\s*(?:iPhone|Samsung|Apple|Sony|MacBook|iPad|AirPods|Anker|Xiaomi)'
    r'\s[^\n]*(?:Photo|Фото|фото)?\s*\d*\s*)+'
)
_PHOTO_LIST_DASH = re.compile(
    r'(?:\n\s*[-•]\s*(?:iPhone|Samsung|Apple|Sony|MacBook|iPad|AirPods|Anker|Xiaomi)'
    r'\s[^\n]*(?:Photo|Фото|фото)?\s*\d*\s*)+'
)
_PHOTO_HEADER = re.compile(r'[Вв]от\s+фото(?:графи[яи])?\s+(?:устройства|товара)\s*:\s*\n?')
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
        for prod in result.get("products", []):
            img = prod.pop("image_url", None)
            total_ph = prod.get("total_photos", 0)
            if img:
                prod["photo_available"] = True
                prod["total_photos"] = total_ph
                if img not in collected_image_urls:
                    collected_image_urls.append(img)
            else:
                prod["total_photos"] = total_ph

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

    Returns matched image URLs or None if no specific match.
    """
    if not variant_images_map or len(variant_images_map) <= 1 or not final_text:
        return None

    combined = (final_text or "").lower() + " " + user_message.lower()
    for vid, vinfo in variant_images_map.items():
        vc = vinfo["color"]
        vt = vinfo["title"]
        if vc and vc in combined:
            logger.info("PHOTO VARIANT MATCH by color=%s vid=%s", vc, vid)
            return vinfo["images"]
        if vt and any(w in combined for w in vt.split() if len(w) > 3):
            logger.info("PHOTO VARIANT MATCH by title=%s vid=%s", vt, vid)
            return vinfo["images"]

    return None


def user_wants_photos(user_message: str) -> bool:
    """Check if user explicitly asked to see photos."""
    return any(kw in user_message.lower() for kw in _PHOTO_KEYWORDS)


async def force_fetch_photos(
    tenant_id, user_message: str, state_context: dict, db: AsyncSession,
) -> list[str]:
    """Force-fetch photos from DB when user asked but AI didn't provide.

    Returns list of image URLs (may be empty).
    """
    from src.ai.truth_tools import get_product_candidates, get_variant_candidates

    product_uuid = None

    # Search DB directly for the product mentioned in user message
    try:
        search_result = await get_product_candidates(tenant_id, user_message, db)
        if search_result.get("found") and search_result.get("products"):
            product_uuid = search_result["products"][0]["product_id"]
            logger.info("PHOTO: found product via search: %s (%s)", search_result["products"][0].get("name"), product_uuid)
    except Exception:
        pass

    # Fallback: use last product from state_context
    if not product_uuid:
        products = state_context.get("products", {})
        for pkey, pinfo in reversed(list(products.items())):
            pid = pinfo.get("product_id")
            if pid:
                product_uuid = pid
                logger.info("PHOTO: fallback to state_context product %s", pkey)
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
            v_title = (vr.get("title") or "").lower()
            v_color = (vr.get("color") or "").lower()

            if v_color and v_color in msg_lower:
                best_imgs = v_imgs
                break
            if any(w in msg_lower for w in v_title.split() if len(w) > 3):
                best_imgs = v_imgs
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


def clean_photo_text(final_text: str, has_photos: bool) -> str:
    """Clean AI text that contradicts photo sending or lists individual photos.

    Only called when photos are actually being sent.
    """
    if not has_photos or not final_text:
        return final_text

    cleaned = final_text
    cleaned = _PHOTO_LIST_PATTERN.sub('', cleaned)
    cleaned = _PHOTO_LIST_DASH.sub('', cleaned)
    cleaned = _PHOTO_HEADER.sub('', cleaned)

    for pat in _PHOTO_DENY_PATTERNS:
        cleaned = pat.sub('', cleaned)

    cleaned = cleaned.strip()
    if cleaned and len(cleaned) > 5:
        return cleaned
    return "Вот фотографии товара:"
