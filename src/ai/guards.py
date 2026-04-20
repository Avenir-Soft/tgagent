"""AI response guards — profanity detection, hallucination checks, language correction.

All code-level checks that catch AI misbehaviour BEFORE sending to user.
Adapted for Easy Tour — tour booking context.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# PROFANITY DETECTION
# ──────────────────────────────────────────────

# Russian mat (core stems + common forms)
_PROFANITY_RU = {
    "блять", "бля", "блядь", "блядина", "блядский",
    "сука", "суки", "сучка", "сучара",
    "хуй", "хуя", "хуё", "хуе", "хуёв", "хуев", "нахуй", "нахуя", "нихуя", "охуел", "охуеть", "похуй",
    "пизда", "пиздец", "пиздёж", "пиздеж", "пиздато", "пиздос", "пиздёш", "пиздеш", "пиздюк",
    "ебать", "ёбаный", "ебаный", "ебал", "ебло", "ебанулся", "ебанутый", "заебал", "заебись",
    "ёб", "ёбтвоюмать", "ебтвоюмать", "уёбок", "уебок", "уёбище", "уебище", "выебать", "съебал",
    "мудак", "мудила", "мудозвон",
    "долбоёб", "долбоеб", "залупа",
    "пидор", "пидорас", "пидарас", "пидираз", "педик", "пидр",
    "дерьмо", "говно", "говнюк",
    "шалава", "шлюха", "потаскуха", "проститутка",
    "гандон", "гондон",
    "битч", "фак", "факю",
    "даун", "дебил", "идиот", "кретин", "урод",
}

# Uzbek profanity (common vulgar words)
_PROFANITY_UZ = {
    "сиктир", "сиқтир", "сиктиргин",
    "сикиш", "сиқиш",
    "онангни", "онангни", "оналаринни",
    "кутак", "кўтак",
    "жинни", "ахмоқ", "ахмок",
    "siktir", "siqtir", "kutok", "kotak", "ko'tak",
    "onangni", "axmoq",
    "sikish", "siqish", "siktirgin",
    "buvini", "onalingni",
}

# English profanity
_PROFANITY_EN = {
    "fuck", "fucking", "fucker", "motherfucker", "mf",
    "shit", "shitty", "bullshit",
    "bitch", "bitches",
    "ass", "asshole", "arsehole",
    "dick", "dickhead",
    "pussy", "cunt",
    "nigga", "nigger",
    "whore", "slut",
    "bastard", "retard",
    "stfu", "gtfo",
}

# Latin transliterations of Russian mat
_PROFANITY_TRANSLIT = {
    "naxuy", "nahuy", "nahui", "naxui",
    "poshel", "pashel", "pashol", "poshol",
    "suka", "cyka",
    "blyat", "blyad", "blya", "bliat",
    "pizdec", "pizdets", "pizda",
    "ebat", "yobany", "yobaniy",
    "mudak", "mudila",
    "pidor", "pidoras", "pidaras",
    "gavno", "govno",
    "zalupa",
    "debil", "urod",
    "gandon", "gondon",
    "huy", "hui", "xuy", "xui",
    "ebal", "ebaniy",
}

_PROFANITY_ALL = _PROFANITY_RU | _PROFANITY_UZ | _PROFANITY_EN | _PROFANITY_TRANSLIT

_PROFANITY_SUBSTRINGS = [
    # Cyrillic
    "хуй", "хуя", "хуе", "пизд", "ебат", "ёбан", "ебан", "блят", "сиктир",
    # Latin
    "siktir", "fuck", "naxu", "nahu", "piзд", "blyat", "blya",
    "xuy", "xui", "pizd",
]


def contains_profanity(text: str) -> bool:
    """Detect profanity in Russian/Uzbek/English text. Code-level check, not LLM."""
    if not text:
        return False
    text_lower = text.lower().replace("ё", "е")
    words = set(text_lower.split())

    # Direct word match
    if words & _PROFANITY_ALL:
        return True

    # Substring match (catches combined words like "иди_нахуй", "fuckoff")
    for sub in _PROFANITY_SUBSTRINGS:
        if sub in text_lower:
            return True

    # Two-word combos: "пошел нахуй" / "иди нахуй" in Latin
    word_list = text_lower.split()
    for i, w in enumerate(word_list):
        if i + 1 < len(word_list):
            combo = w + word_list[i + 1]
            if any(sub in combo for sub in ["naxu", "nahu", "fuck"]):
                return True

    return False


# ──────────────────────────────────────────────
# HALLUCINATION DETECTION
# ──────────────────────────────────────────────

# Price pattern: "1 234 567" or "1,234,567"
_PRICE_PATTERN = re.compile(r'\d{1,3}[\s,]\d{3}[\s,]\d{3}')
_PRICE_EXTRACT = re.compile(r'(\d{1,3}[\s,]\d{3}[\s,]\d{3})')

# Russian markers for language mismatch detection
_RUSSIAN_MARKERS = [
    "отлично", "готово", "ваш заказ", "если что",
    "обращайтесь", "что-нибудь ещё", "спасибо за",
]

# Fabricated tour details (should NEVER appear unless tools returned them)
_FABRICATED_TOUR_PATTERNS = [
    re.compile(r'(?:otel|отель|гостиница|hotel)\s*[-—:]?\s*\d+\s*(?:yulduz|звёзд|star)', re.IGNORECASE),
    re.compile(r'(?:aviachipta|авиабилет|flight)\s*[-—:]?\s*(?:kiritilgan|включен|included)', re.IGNORECASE),
]

# Fabricated metrics — AI invents heights, distances, travel times not in DB
_FABRICATED_METRIC_PATTERNS = [
    # Height: "30 metr", "30 метров", "30 meters"
    re.compile(r'\d+\s*(?:metr|метр|meters?|feet|fut)\b', re.IGNORECASE),
    # Distance: "50 km", "50 километров"
    re.compile(r'\d+\s*(?:km|км|километр|kilom)', re.IGNORECASE),
    # Travel time: "1.5 soat", "2 часа", "1,5-2 soat"
    re.compile(r'\d[\d,.\-–]*\s*(?:soat|час|hour|minut|минут|daqiqa)', re.IGNORECASE),
    # Temperature: "20 gradus", "20°C"
    re.compile(r'\d+\s*(?:gradus|градус|°[CF])', re.IGNORECASE),
]


def detect_hallucinations(
    final_text: str,
    tools_called: set[str],
    state_context: dict,
    booking_before_ai: dict,
    detected_lang: str,
) -> str | None:
    """Check AI response for hallucinations and return corrected text or None.

    Returns corrected text if hallucination detected, None if response is OK.
    """
    if not final_text:
        return None

    text_lower = final_text.lower()

    # --- 1. Price shown without price tools ---
    has_price_pattern = bool(_PRICE_PATTERN.search(final_text))
    price_tools = {"get_variant_candidates", "check_order_status", "get_product_candidates", "create_order_draft"}
    if has_price_pattern and not (tools_called & price_tools):
        known_prices: set[int] = set()
        for prod_info in state_context.get("products", {}).values():
            for v in prod_info.get("variants", []):
                try:
                    known_prices.add(int(float(v.get("price", 0))))
                except (ValueError, TypeError):
                    pass
            pr = prod_info.get("price_range", "")
            if pr:
                for p in re.findall(r'(\d+)', str(pr)):
                    try:
                        known_prices.add(int(p))
                    except ValueError:
                        pass
        found_prices = _PRICE_EXTRACT.findall(final_text)
        for fp in found_prices:
            try:
                price_int = int(fp.replace(" ", "").replace(",", ""))
                if price_int > 100000 and price_int not in known_prices and known_prices:
                    logger.warning("AI showed price %s not from tools — potential hallucination", price_int)
                    break
            except ValueError:
                pass

    # --- 2. Fabricated tour details ---
    if "get_variant_candidates" not in tools_called:
        for pattern in _FABRICATED_TOUR_PATTERNS:
            if pattern.search(final_text):
                logger.warning("AI fabricated tour details (pattern: %s) — overriding response", pattern.pattern)
                corrections = {
                    "ru": "Я могу показать только доступные туры и цены. Для подробностей используйте инструменты. Чем ещё помочь?",
                    "uz_cyrillic": "Мен фақат мавжуд турлар ва нархларни кўрсата оламан. Яна нима керак?",
                    "uz_latin": "Men faqat mavjud turlar va narxlarni ko'rsata olaman. Yana nima kerak?",
                    "en": "I can only show available tours and prices. What else can I help with?",
                }
                return corrections.get(detected_lang, corrections["uz_latin"])

    # --- 2b. Fabricated metrics (heights, distances, travel times) ---
    # These facts are NOT in our database — AI must not invent them
    for pattern in _FABRICATED_METRIC_PATTERNS:
        match = pattern.search(final_text)
        if match:
            matched_text = match.group()
            # Allow if it's from variant attributes_json (tool returned it)
            if "get_variant_candidates" in tools_called:
                continue
            # Allow known quantities: seat counts, prices, participant counts
            # Only block descriptive metrics (height, distance, time)
            logger.warning("AI fabricated metric '%s' — stripping from response", matched_text)
            # Remove the fabricated sentence containing the metric
            sentences = re.split(r'[.!]\s+', final_text)
            cleaned = [s for s in sentences if not pattern.search(s)]
            if cleaned:
                final_text_clean = ". ".join(cleaned)
                if not final_text_clean.endswith((".", "!", "?")):
                    final_text_clean += "."
                return final_text_clean

    # --- 3. Language mismatch correction ---
    corrected = _fix_language_mismatch(final_text, text_lower, detected_lang)
    if corrected:
        return corrected

    return None


def _fix_language_mismatch(final_text: str, text_lower: str, detected_lang: str) -> str | None:
    """Fix AI responding in wrong language. Returns corrected text or None."""
    if detected_lang == "uz_cyrillic" and final_text:
        has_russian = sum(1 for m in _RUSSIAN_MARKERS if m in text_lower)
        has_uz = any(c in final_text for c in "ўқғҳ")
        if has_russian >= 2 and not has_uz:
            logger.warning("AI responded in Russian instead of uz_cyrillic — fixing")
            if any(w in text_lower for w in ["готово", "обновлён", "обращайтесь"]):
                return "Тайёр! Буюртмангиз янгиланди 👍 Яна нима керак бўлса, ёзинг!"
            elif any(w in text_lower for w in ["спасибо", "покупку", "бронь"]):
                return "Раҳмат! Броningиз учун ташаккур 🙏"

    elif detected_lang == "uz_latin" and final_text:
        cyrillic_count = sum(1 for c in final_text if "\u0400" <= c <= "\u04FF")
        latin_count = sum(1 for c in final_text if "a" <= c.lower() <= "z")
        if cyrillic_count > latin_count and cyrillic_count > 10:
            logger.warning("AI responded in Cyrillic instead of uz_latin — fixing")
            if any(w in text_lower for w in ["готово", "обновлён", "обращайтесь", "тайёр"]):
                return "Tayyor! Buyurtmangiz yangilandi 👍 Yana nima kerak bo'lsa, yozing!"

    return None


def strip_markdown(text: str) -> str:
    """Strip markdown that Telegram renders poorly — links, headers, bold markers."""
    # Links: ![alt](url) → alt, [text](url) → text
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Headers: ### Title → Title
    text = re.sub(r'^#{1,4}\s+', '', text, flags=re.MULTILINE)
    # Bold: **text** → text
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    return text


# Keep old name for backward compat
strip_markdown_links = strip_markdown
