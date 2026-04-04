"""Language detection and deterministic greeting handler.

Detects message language (ru, uz_cyrillic, uz_latin, en) and handles
pure greeting messages without invoking the LLM.
"""

import random as _random


# ──────────────────────────────────────────────
# LANGUAGE DETECTION
# ──────────────────────────────────────────────

def _detect_language(text: str, current_language: str = "ru") -> str:
    """Detect message language and script: 'ru', 'uz_cyrillic', 'uz_latin', 'en'.

    Returns specific script for Uzbek to ensure AI responds in matching script.
    Falls back to current conversation language for ambiguous messages.
    """
    if not text:
        return current_language
    stripped = text.strip()
    text_lower = stripped.lower()
    word_list = text_lower.replace("\u2019", "'").replace("\u2018", "'").replace("'", "'").split()
    words = set(word_list)

    # --- Check STRONG Uzbek markers first (even for single words) ---

    # Uzbek-specific Cyrillic characters: ў, қ, ғ, ҳ — always Uzbek
    if any(c in text for c in "ўқғҳ"):
        return "uz_cyrillic"

    # Uzbek Cyrillic plural/verb suffixes that Russian doesn't have
    uz_suffixes_cyrillic = ["лар", "лер", "ларни", "ларин", "лик", "чил", "айми", "амиз", "синг"]
    for w in word_list:
        for suf in uz_suffixes_cyrillic:
            if w.endswith(suf) and len(w) > len(suf) + 2:
                return "uz_cyrillic"

    # Single strong Uzbek Cyrillic words (even alone)
    uz_strong_cyrillic = {
        "салом", "рахмат", "керак", "нима", "кани", "борми", "йўқ", "яхши",
        "кўрсат", "кейин", "ассалому", "ёрдам", "олай", "берай",
        "болди", "булди", "чунарли", "кушвурин", "кушворин", "жунатинг",
        "жунатвурасиз", "расмийлаштирамизми", "урвурин", "олдинги",
        "зааказ", "закажи", "маҳсулот", "мавжуд", "буюртма",
    }
    if words & uz_strong_cyrillic:
        return "uz_cyrillic"

    # Single strong Uzbek Latin words (even alone)
    uz_strong_latin = {
        "salom", "rahmat", "kerak", "nima", "kani", "bormi", "yoq", "yaxshi",
        "keyin", "assalomu", "oka", "aka", "uka", "qalesan", "qalaysiz",
        "yaxshimisiz", "zakaz", "buyurtma", "tovar", "manga", "menga",
        "qimoqchiman", "qimoqchidim", "mavjud", "narxi", "narx",
        # Common conversational words
        "buvini", "buni", "shuni", "etim", "kere", "kerakdi",
        "rangli", "ranglisi", "rangdagi", "qanday", "qaysi",
        "olaman", "olsam", "beraman", "bering", "qoshvoring",
        "oformit", "rasmiy", "kuk", "qora", "oq",
        # Colors and common adjectives
        "kok", "ko'k", "ko'kdan", "ko'kning",
        # Common Uzbek words that get missed
        "faqat", "faqqat", "lekin", "ammo", "endi",
        "nechta", "qancha", "hammasi", "barchasi",
        "uzbecha", "o'zbekcha", "uzbek", "uzbekcha",
        "gapiring", "gapir", "gapiryapsiz",
        # Cart/order words
        "korzina", "korzinaga", "korzinani",
        "savat", "savatcha", "savatchaga",
        "otamiz", "otiylik",
        # Direction words
        "bopti", "mayli", "tamom",
        # Verbs and common phrases
        "buzilgan", "keldi", "kelgan", "ketdi", "ketgan",
        "qaytaring", "qaytarish", "qaytarib", "qaytardi",
        "ishlamaydi", "ishlamayd", "ishlamayapti",
        "yerdamisiz", "yerdamiz", "bormisiz", "bordingiz",
        "oldim", "olgandim", "olyapman", "olganman",
        "sotib", "sotiladi", "sotasiz", "sotasizmi",
        "yozing", "yozaman", "yozdim",
        "chiqdi", "chiqmadi", "tushdi", "tushunmadim",
        "arzon", "qimmat", "chegirma", "kafolat",
        "dostavka", "yetkazib", "yetkazasiz",
        # Handoff / operator request
        "chaqir", "chaqiring", "chaqiramiz", "operator",
        "odam", "odamga", "menejer", "menejerni",
    }
    if words & uz_strong_latin:
        return "uz_latin"

    # --- Strong Russian markers (must be checked BEFORE short message fallback!) ---
    # Without this, "Привет" in a conversation with current_language=uz_cyrillic
    # falls through to the fallback and stays uz_cyrillic.
    ru_strong_words = {
        "привет", "здравствуйте", "здрасте", "здарова", "добрый",
        "хочу", "хотел", "хотела", "можете", "можно", "пожалуйста",
        "спасибо", "подскажите", "покажите", "сколько", "почему",
        "заказать", "говорить", "говорите", "русском", "русски",
        "скажите", "помогите", "нужен", "нужна", "нужно",
        "оформить", "доставка", "доставку",
    }
    if words & ru_strong_words:
        return "ru"

    # --- English detection ---
    en_words = {
        "hello", "hi", "hey", "order", "want", "need", "buy", "price",
        "delivery", "please", "thanks", "thank", "how", "much", "show",
        "cart", "checkout", "cancel", "wanna", "gonna",
    }
    if words & en_words:
        # Check it's actually mostly Latin (not Russian with borrowed words)
        latin_count = sum(1 for c in text_lower if "a" <= c <= "z")
        if latin_count > len(text_lower) * 0.4:
            return "en"

    # Short messages (1-2 words or < 5 chars) with no strong markers → keep current language
    if len(stripped) < 5 or len(word_list) <= 1:
        return current_language

    # --- Uzbek Latin markers (extended) ---
    uz_latin_words = {
        "kerak", "narx", "qancha", "buyurtma", "rahmat", "salom",
        "yaxshi", "olaman", "beraman", "menga", "sizga", "nima", "qaysi",
        "uchun", "bilan", "xarid", "mahsulot", "sotib", "olish",
        "yetkazib", "berish", "manzil", "raqam", "tanlang",
        "qoshish", "olib", "tashlash", "holat", "qaytarish",
        "bormi", "bering", "arzon", "qimmat", "yoq", "kani",
        "nimaga", "bor", "ber", "yoqmi", "shuni", "shu",
        "qo'sh", "tashla", "oka", "aka", "uka",
        "qalesan", "qalaysiz", "yaxshimisiz", "zakaz", "tovar",
        "manga", "qimoqchiman", "qimoqchidim", "mavjud", "ko'rsat",
        "variantlar", "telefonlar", "soatlar", "narsalar",
        "qorasidan", "oqidan", "rangi", "narxi",
        "buni", "buvini", "shuni", "etim", "kere", "kerakdi",
        "rangli", "ranglisi", "rangdagi", "kuk", "qora", "oq",
        "oformit", "rasmiy", "olsam", "qoshvoring",
    }
    if words & uz_latin_words:
        return "uz_latin"

    # Uzbek Latin suffix patterns
    uz_latin_suffixes = [
        "dan", "dagi", "dek", "lar", "ler", "dim", "man", "miz", "siz",
        "gan", "kan", "ing", "adi", "ydi", "chi", "lik", "sini", "ning",
    ]
    for w in word_list:
        if len(w) > 4:
            for suf in uz_latin_suffixes:
                if w.endswith(suf) and any("a" <= c <= "z" for c in w[:3]):
                    return "uz_latin"

    # Check for Uzbek Latin apostrophe patterns (o', g')
    uz_patterns = ["o'", "g'", "o\u2019", "g\u2019"]
    latin_count = sum(1 for c in text if "a" <= c.lower() <= "z")
    if latin_count > 3:
        if any(p in text_lower for p in uz_patterns):
            return "uz_latin"

    # --- Uzbek Cyrillic markers ---
    uz_cyrillic_markers = [
        "салом", "ассалому", "рахмат", "керак", "нарх",
        "буюртма", "менга", "сизга", "нима", "яхши", "манзил",
        "кани", "кевосан", "бовоти", "олб", "таша",
        "курсат", "ёрдам", "узбеч",
        "гаплаш", "тушун", "кечир", "сурама", "берай",
        "олай", "нарса", "ёзинг",
    ]
    for marker in uz_cyrillic_markers:
        if marker in text_lower:
            return "uz_cyrillic"

    # Uzbek informal Cyrillic (written without special chars)
    uz_informal_cyrillic = [
        "канча", "нарси", "бераман", "оламан",
        "олб", "йок", "бовот", "сурадим", "езган",
        "олди", "кирди", "чикди", "булди",
    ]
    for marker in uz_informal_cyrillic:
        if marker in text_lower:
            return "uz_cyrillic"

    # --- English (longer phrases) ---
    if latin_count > len(stripped) * 0.6 and len(word_list) >= 2:
        # Mostly Latin text with 2+ words and no Uzbek markers
        # IMPORTANT: don't flip from Uzbek Latin to English based on script alone
        # Users often write Uzbek with technical terms (512gb, RTX, etc.) that look Latin
        if current_language in ("uz_latin", "uz_cyrillic"):
            return current_language
        return "en"

    # Cyrillic text without Uzbek markers
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04FF")
    if cyrillic > 0:
        # If user was already in Uzbek Cyrillic, keep it unless clear Russian words
        if current_language == "uz_cyrillic":
            ru_only_markers = ["пожалуйста", "спасибо", "здравствуйте", "подскажите", "можно", "хочу", "покажите", "сколько", "почему"]
            if not any(m in text_lower for m in ru_only_markers):
                return "uz_cyrillic"
        return "ru"

    return current_language


# ──────────────────────────────────────────────
# DETERMINISTIC GREETING HANDLER
# ──────────────────────────────────────────────

# Greeting patterns per language
_GREETING_PATTERNS = {
    "ru": ["привет", "здравствуйте", "добрый день", "добрый вечер", "доброе утро", "ку", "хеллоу", "хай", "здрасте", "здарова", "здаров", "здоров", "здорова", "прив", "приветик"],
    "uz_cyrillic": ["салом", "ассалому алейкум", "ассалом", "хуш келибсиз"],
    "uz_latin": ["salom", "assalomu alaykum", "assalom", "xush kelibsiz"],
    "en": ["hi", "hello", "hey", "good morning", "good evening", "good afternoon", "howdy"],
}

# "How are you" patterns
_HOW_ARE_YOU_PATTERNS = {
    "uz_cyrillic": ["яхшимисиз", "қалайсиз", "қалесан", "яхшимисан", "яхшимсиз"],
    "uz_latin": ["yaxshimisiz", "qalaysiz", "qalesan", "yaxshimisan", "yaxshimsiz"],
    "ru": ["как дела", "как ты", "как вы"],
    "en": ["how are you", "how's it going", "how are things"],
}

# Greeting responses — deterministic, grammatically correct
_GREETING_RESPONSES = {
    "ru": [
        "Привет! Чем могу помочь?",
        "Здравствуйте! Что подобрать?",
        "Привет! Какой товар интересует?",
    ],
    "uz_cyrillic": [
        "Ассалому алейкум! Қандай ёрдам бера оламан?",
        "Ассалому алейкум! Қайси товаримиз қизиқтиряпти?",
        "Салом! Қандай товар керак?",
    ],
    "uz_latin": [
        "Assalomu alaykum! Qanday yordam bera olaman?",
        "Assalomu alaykum! Qaysi tovarimiz qiziqtiryapti?",
        "Salom! Qanday tovar kerak?",
    ],
    "en": [
        "Hi! How can I help you?",
        "Hello! What product are you looking for?",
        "Hey! What can I show you?",
    ],
}

# "How are you" responses
_HOW_ARE_YOU_RESPONSES = {
    "ru": [
        "Хорошо, спасибо! Чем могу помочь?",
    ],
    "uz_cyrillic": [
        "Яхшиман, раҳмат! Сизга қандай ёрдам бера оламан?",
        "Раҳмат, яхши! Қандай товар керак?",
    ],
    "uz_latin": [
        "Yaxshiman, rahmat! Sizga qanday yordam bera olaman?",
        "Rahmat, yaxshi! Qanday tovar kerak?",
    ],
    "en": [
        "I'm good, thanks! How can I help you?",
    ],
}


def _check_greeting(text: str, language: str) -> str | None:
    """Check if message is a greeting and return a deterministic response.

    Returns response string or None if not a greeting.
    This bypasses the LLM entirely to avoid bad grammar in Uzbek.
    Only triggers for PURE greeting messages — if the message also contains
    a product query or request, skip greeting and let LLM handle everything.
    """
    text_lower = text.strip().lower()
    # Remove punctuation for matching
    clean = text_lower.replace("!", "").replace("?", "").replace(".", "").replace(",", "").strip()
    clean_words = clean.split()

    # Only handle short greeting messages (≤ 5 words) — longer messages go to LLM
    if len(clean_words) > 5:
        return None

    # If message has NON-greeting content (product query, request, etc.) → skip greeting,
    # let LLM handle the full message. "ассалому алейкум айфон борми" → LLM, not greeting.
    _ALL_GREETING_WORDS = {
        "привет", "приветик", "прив", "здравствуйте", "добрый", "день", "вечер", "утро", "доброе", "ку",
        "хеллоу", "хай", "здрасте", "здарова", "здаров", "здоров", "здорова",
        "салом", "ассалому", "алейкум", "ассалом", "хуш", "келибсиз",
        "salom", "assalomu", "alaykum", "assalom", "xush", "kelibsiz",
        "hi", "hello", "hey", "good", "morning", "evening", "afternoon", "howdy",
        "яхшимисиз", "қалайсиз", "қалесан", "яхшимисан", "яхшимсиз",
        "yaxshimisiz", "qalaysiz", "qalesan", "yaxshimisan", "yaxshimsiz",
        "как", "дела", "ты", "вы",
        "how", "are", "you",
        "ока", "aka", "uka", "брат", "бро",
    }
    non_greeting_words = [w for w in clean_words if w not in _ALL_GREETING_WORDS]
    if non_greeting_words:
        # Message has content beyond greeting → let LLM handle it all
        return None

    clean_words_set = set(clean_words)

    # Check "how are you" first (they may include a greeting)
    for lang, patterns in _HOW_ARE_YOU_PATTERNS.items():
        for pattern in patterns:
            pattern_words = set(pattern.split())
            # Multi-word: check all words present. Single-word: check in word set.
            if len(pattern_words) > 1:
                if pattern_words <= clean_words_set:
                    responses = _HOW_ARE_YOU_RESPONSES.get(language, _HOW_ARE_YOU_RESPONSES["ru"])
                    return _random.choice(responses)
            else:
                if pattern in clean_words_set:
                    responses = _HOW_ARE_YOU_RESPONSES.get(language, _HOW_ARE_YOU_RESPONSES["ru"])
                    return _random.choice(responses)

    # Check pure greetings — match whole words only
    for lang, patterns in _GREETING_PATTERNS.items():
        for pattern in patterns:
            pattern_words = set(pattern.split())
            if len(pattern_words) > 1:
                if pattern_words <= clean_words_set:
                    responses = _GREETING_RESPONSES.get(language, _GREETING_RESPONSES["ru"])
                    return _random.choice(responses)
            else:
                if pattern in clean_words_set:
                    responses = _GREETING_RESPONSES.get(language, _GREETING_RESPONSES["ru"])
                    return _random.choice(responses)

    return None
