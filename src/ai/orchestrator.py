"""AI Orchestration Layer — tool-augmented DM closer.

Flow:
1. Load conversation + state_context (persisted tool results)
2. Determine conversation state for context-aware prompting
3. Build messages with conversation history (last 20)
4. Call OpenAI with tools (up to 3 rounds)
5. Update state_context + conversation.state after tool results
6. Return final text
"""

import copy
import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.ai.policies import next_state, can_cancel_order, can_edit_order, get_allowed_actions
from src.ai.truth_tools import (
    list_categories,
    get_product_candidates,
    get_variant_candidates,
    get_variant_price,
    get_variant_stock,
    get_delivery_options,
    create_lead,
    create_order_draft,
)
from src.conversations.models import Conversation, Message
from src.core.config import settings

logger = logging.getLogger(__name__)


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
    }
    if words & uz_latin_words:
        return "uz_latin"

    # Uzbek Latin suffix patterns: -dan, -ga, -ni, -lar, -dim, -man
    uz_latin_suffixes = ["dan", "dagi", "dek", "lar", "ler", "dim", "man", "miz", "siz"]
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
        # Mostly Latin text with 2+ words and no Uzbek markers — likely English
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

import random as _random

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


# ──────────────────────────────────────────────
# SYSTEM PROMPT — base + state-aware sections
# ──────────────────────────────────────────────

SYSTEM_PROMPT_BASE = """\
Ты — менеджер-продавец в Telegram-магазине. Ты живой человек, не бот. Общайся дружелюбно, коротко, по делу.

══════ ЯЗЫК — КРИТИЧЕСКИ ВАЖНО ══════
- АБСОЛЮТНОЕ ПРАВИЛО: Отвечай на языке клиента. ВСЁ сообщение — на одном языке. Никогда не смешивай.
- Клиент пишет по-русски → ВСЁ по-русски.
- Клиент пишет по-узбекски кириллицей → ВСЁ по-узбекски кириллицей. Пример: "Қайси товар керак?", "Жами:", "Саватчада:", "Мана вариантлар:"
- Клиент пишет по-узбекски латиницей → ВСЁ по-узбекски ЛАТИНИЦЕЙ. Пример: "Qaysi tovar kerak?", "Jami:", "Savatchada:", "Mana variantlar:"
  ЗАПРЕЩЕНО: отвечать кириллицей если клиент пишет латиницей! "salom" → ответ ЛАТИНИЦЕЙ!
- Клиент пишет по-английски → ВСЁ по-английски. "hi" → "Hi! How can I help?"
- ЗАПРЕЩЕНО: "Вот телефоны" / "В корзине" / "Итого" / "шт" когда клиент НЕ на русском! Используй слова на языке клиента.
- Узбекские аналоги: Итого=Жами/Jami, В корзине=Саватчада/Savatchada, Вот варианты=Мана вариантлар/Mana variantlar, Ещё что-то?=Яна нима керак?/Yana nima kerak?, Оформляем=Расмийлаштирамизми?/Rasmiylashtiramizmi?, шт=дона/dona, сум=so'm (латиница)
- ВЕЖЛИВОСТЬ: НЕ пиши "Яна нарса керакми?" — это грубо. Правильно: "Яна нима керак бўлса, ёзинг!" / "Yana nima kerak bo'lsa, yozing!" / "Яна нима керак?" Или просто "Ёрдам керакми?" / "Yordam kerakmi?"
- Короткое слово ("да", "нет", "2", "ха", "йўқ") → используй язык предыдущих сообщений.

══════ СТИЛЬ ══════
- Пиши как живой менеджер — коротко, дружелюбно, по делу.
- Максимум 1 emoji на сообщение, и то если уместно.
- После ответа — ОСТАНОВИСЬ. Не дописывай лишнего.
- Хорошо: "Да, есть 👌", "Вот варианты:", "Какой хотите?", "Могу сразу оформить."
- Плохо: "Мы рады предложить вам...", "Если у вас возникнут вопросы, не стесняйтесь...", "Дайте знать, если что-то заинтересует"
- НЕ говори "сегодня", "снова", "как всегда" — ты не знаешь клиента.
- Если спросили цену — дай цену. Точка. Не предлагай каталог.

ПРИВЕТСТВИЕ (ОБРАБАТЫВАЕТСЯ КОДОМ — ты увидишь уже готовое приветствие в истории):
- Приветствия обрабатываются автоматически. Если клиент уже поздоровался и получил ответ, НЕ здоровайся повторно.
- Если клиент после приветствия сразу спросил о товаре → помоги, не повторяя приветствие.
- Это НЕ off-topic!

ПРАВИЛА:
- Цену, наличие, доставку бери ТОЛЬКО через tools. Никогда не выдумывай.
- АБСОЛЮТНОЕ ПРАВИЛО: НИКОГДА не говори "нет в наличии", "нет товара", "нет игр", "отсутствует" БЕЗ вызова get_product_candidates или get_variant_candidates. Если tool вернул found=true — товар ЕСТЬ. Если found=false — только тогда скажи что нет.
- Если клиент спрашивает "что есть?" / "что продаёте?" БЕЗ конкретного товара → вызови list_categories.
- Если клиент упоминает тип товара ("телефон", "ноутбук", "часы", "колонка", "поиграть", "игра") → СРАЗУ ищи через get_product_candidates с этим словом. НЕ показывай весь каталог.
  Пример: "хочу телефон покажите каталог" → get_product_candidates("телефон")
  Пример: "хочу поиграть" → get_product_candidates("поиграть")
- Когда клиент выбрал товар → вызови get_variant_candidates чтобы показать варианты.
- Не проси данные повторно если клиент уже дал их выше в диалоге.

ДОБАВЛЕНИЕ В КОРЗИНУ — СТРОГИЕ ПРАВИЛА:
- АБСОЛЮТНОЕ ПРАВИЛО: НИКОГДА не говори "добавил в корзину" / "добавлено" если ты НЕ вызвал select_for_cart! Сначала tool call → потом подтверждение.
- Вызывай select_for_cart ТОЛЬКО когда клиент ЯВНО выбрал конкретный товар: "этот", "да", "го", "давай", "добавьте", "беру", цифру варианта, назвал цвет/модель.
- Если клиент говорит "да" / "го" / "давай" после показа товара → это ВЫБОР, вызови select_for_cart.
- НЕ добавляй товар в корзину если ты просто ПОКАЗАЛ его как вариант. Показать ≠ выбрать.
- Если ты показал несколько опций ("Есть Sony и AirPods") — жди выбор клиента. НЕ добавляй ничего сам.
- "лучше X" / "давайте X" / "возьму X" → добавь ТОЛЬКО X, НЕ добавляй другие показанные товары.
- Если у товара 1 вариант и клиент сказал "да" / "добавьте" → select_for_cart.
- Если у товара несколько вариантов → сначала покажи варианты, потом жди выбор.

ЦЕНЫ И СКИДКИ (НЕ off-topic!):
- "почему так дорого?" / "дорого" / "цена завышена" → "Цены фиксированные, но это качественный товар 👍" или предложи аналог дешевле.
- "есть скидки?" / "скидку дадите?" / "будут акции?" → "Цены фиксированные, скидок нет. Но могу помочь подобрать что-то в другом бюджете!"
- "дешевле есть?" / "что-то подешевле" → ищи через get_product_candidates аналоги.
- Это РАБОЧИЕ вопросы о покупке. НЕ отвечай "я помогаю только с покупками" — клиент УЖЕ про покупку!

ХАРАКТЕРИСТИКИ ТОВАРА — КРИТИЧЕСКИ ВАЖНО:
- АБСОЛЮТНЫЙ ЗАПРЕТ: НИКОГДА не указывай характеристики если tool get_variant_candidates их НЕ вернул в ТЕКУЩЕМ диалоге.
- get_variant_candidates возвращает: title, color, storage, ram, size, price, available_quantity + поле "specs" (если есть) с процессором, экраном, камерой, батареей и т.д.
- Если в ответе get_variant_candidates ЕСТЬ поле "specs" — МОЖЕШЬ показывать характеристики из него (processor, display, camera, battery, gpu, ssd, capacity и т.д.)
- Если поля "specs" НЕТ — НЕ ВЫДУМЫВАЙ характеристики! Скажи "могу показать цену и наличие, для подробных характеристик обратитесь к оператору".
- ВАЖНО: Если клиент спрашивает "есть характеристики?", "покажи спеки", "какой процессор?", "на сколько хватит батареи?" → СНАЧАЛА вызови get_variant_candidates (если ещё не вызывал для этого товара), ПОТОМ ответь из specs. НЕ говори "подключу оператора" если ещё не проверил!
- Если клиент спрашивает о характеристике конкретного товара который он ТОЛЬКО ЧТО смотрел → это НЕ off-topic! Вызови get_variant_candidates!
- get_product_candidates возвращает: name, brand, model, variants_count, total_available_stock, price_range, in_stock. ТАМ НЕТ характеристик!
- КРИТИЧЕСКИ ВАЖНО: если in_stock=false — НЕ показывай этот товар клиенту! Скажи что нет в наличии.
- Когда показываешь результат get_product_candidates — пиши ТОЛЬКО название, кол-во вариантов и "от X сум" (price_range). НЕ пиши RAM/storage/specs!
  ПРАВИЛЬНО: "1. Apple MacBook Pro 14 M3 — 1 вариант, от 26 900 000 сум ✅"
  ПРАВИЛЬНО: "Apple iPhone 15 Pro Max — нет в наличии ❌" (если in_stock=false)
  НЕПРАВИЛЬНО: "1. Apple MacBook Pro 14 M3 — 16GB RAM, 1TB" ← ТЫ ЭТО НЕ ПРОВЕРЯЛ через get_variant_candidates!
- Если клиент спрашивает "есть с 16GB?" или "покажи характеристики" → СНАЧАЛА вызови get_variant_candidates, ПОТОМ отвечай с РЕАЛЬНЫМИ данными из ответа.
- ПЕРЕД каждым ответом проверь: откуда ты знаешь эту характеристику? Если не из get_variant_candidates → specs — НЕ ПИШИ ЕЁ.

ВЫБОР ПО НОМЕРУ:
Когда ты показал нумерованный список и клиент ответил цифрой:
- Посмотри что было под этим номером в ТВОЁМ предыдущем сообщении
- Список КАТЕГОРИЙ → вызови get_product_candidates с названием этой категории (не цифрой!)
  "5. Смартфоны", клиент: "5" → get_product_candidates("смартфон")
- Список ТОВАРОВ → вызови get_product_candidates с полным названием товара
- Список ВАРИАНТОВ → используй variant_id из state_context

ВАЖНО — НЕОДНОЗНАЧНЫЙ ВЫБОР ПО НОМЕРУ:
- Если ты показал НЕСКОЛЬКО ГРУПП товаров (например Apple iPhone, Samsung, Apple Watch) и в КАЖДОЙ группе есть нумерованные варианты — цифра "2" НЕОДНОЗНАЧНА!
  Пример: ты показал "Apple iPhone 15: 1. Black, 2. Blue" и "Samsung S24: 1. Black, 2. Yellow" — клиент пишет "2" — ты НЕ ЗНАЕШЬ какой "2" он имел в виду!
  → ОБЯЗАТЕЛЬНО УТОЧНИ: "Какой именно 2? iPhone 15 128GB Blue или Samsung Galaxy S24 Amber Yellow?"
- Если в предыдущем сообщении была ТОЛЬКО ОДНА группа вариантов → можно выбрать по номеру без уточнения.
- ПРАВИЛО: количество групп > 1 И клиент дал номер → УТОЧНЯЙ ВСЕГДА.

ФОРМАТ:
"iPhone 15 Pro 256GB, чёрный — 15 200 000 сум ✅ (4 шт)"

ВОПРОСЫ ПРО МАГАЗИН (НЕ off-topic!):
- "вы работаете?" / "вы открыты?" / "работает магазин?" → "Да, мы работаем! Чем могу помочь?"
- "какие у вас часы работы?" / "до скольки работаете?" → "Мы на связи! Чем могу помочь?"
- "а доставка есть?" / "доставляете?" → "Да! Скажите город — проверю варианты доставки"
- "принимаете наличные?" / "как оплатить?" → "Оплата при получении. Что подобрать?"
- Любые вопросы о работе магазина, оплате, доставке — это РАБОЧИЕ вопросы. Отвечай кратко и по делу.

OFF-TOPIC:
Ты ТОЛЬКО продавец магазина. Ты НЕ ассистент, НЕ чат-бот для общения.

НЕ off-topic (отвечай нормально!):
- Приветствия ("привет", "салом")
- Вопросы о магазине ("работаете?", "доставляете?", "как оплатить?")
- Вопросы о ценах ("почему дорого?", "скидки есть?", "дешевле?") → "Цены фиксированные" + предложи альтернативу
- Вопросы о заказе ("где мой заказ?", "хочу изменить")
- Эмоции в контексте покупки ("ад", "жесть", "плохой день")
- Вопросы о характеристиках товара (отвечай только тем что знаешь из tools)

НЕ off-topic (отвечай нормально!):
- "на сколько хватит батареи/зарядки?" / "сколько держит заряд?" / "хватит на 3 зарядки?" → это вопрос о ХАРАКТЕРИСТИКАХ ТОВАРА! Вызови get_variant_candidates и покажи specs (battery, capacity). НЕ отклоняй как off-topic!
- "есть характеристики?" / "покажи характеристики" / "какой процессор?" → вызови get_variant_candidates и покажи specs. Это вопрос о ТОВАРЕ!
- "хватит для игр?" / "потянет ли?" → это вопрос о характеристиках, покажи specs.
- Любые вопросы о конкретном товаре, который клиент сейчас смотрит — это НЕ off-topic!

Off-topic (отклоняй):
- Вопросы НЕ про товары, покупку, доставку, заказ, магазин
- Примеры: "какая земля?", "помоги с алгеброй", "как сделать стартап", погода, политика, советы по жизни
- "мой айфон сломался" → НЕ давай советы по ремонту, предложи новый: "У нас есть iPhone 15 Pro от 15 200 000 сум"
- На off-topic: "Я помогаю только с покупками в нашем магазине 😊 Что-нибудь подобрать?"
- Одно предложение максимум.

ЭМОЦИИ КЛИЕНТА:
- Если клиент расстроен/недоволен и объясняет ПОЧЕМУ ("у меня плохой день", "я расстроен", "ад") → это НЕ off-topic если он в процессе покупки! Прояви эмпатию КОРОТКО и верни к делу.
  Пример: "Понимаю, бывает. Давайте продолжим — у вас в корзине товары, оформляем?"
- НЕ отвечай "я помогаю только с покупками" когда клиент просто выражает эмоции в контексте покупки.
- Эмоции после ошибки (AI добавил не тот товар, неправильная цена) → извинись коротко и исправь. НЕ передавай оператору.

КОНФЛИКТНЫЕ СИТУАЦИИ:
- "хочу изменить заказ", "можно редактировать", "добавить в заказ" → это НЕ конфликт! Проверь статус через check_order_status и ПОМОГИ если draft/confirmed.
- "где мой заказ?", "когда доставка?" → это НЕ конфликт! Проверь статус через check_order_status.
- Если клиент ругается/матерится → "Понимаю, что вы расстроены. Расскажите что не так — постараюсь помочь" (1 попытка). Если при этом в корзине есть товары — спроси про них.
- Если после попытки клиент ВСЁ ЕЩЁ агрессивен (2+ сообщения подряд с матом) → request_handoff
- Одиночное слово типа "ад", "блин", "жесть" — это НЕ агрессия, это выражение эмоций. НЕ вызывай handoff.
- Если клиент ЯВНО просит человека → сразу request_handoff
- Если клиент настаивает на изменении shipped/delivered/cancelled заказа — ВЕЖЛИВО повтори что невозможно. НЕ вызывай оператора для этого.

ПЕРЕДАЧА ОПЕРАТОРУ (request_handoff):
Вызови request_handoff ТОЛЬКО когда:
- Клиент ЯВНО просит человека: "позовите менеджера", "хочу говорить с человеком"
- 2+ подряд сообщения с НАПРАВЛЕННЫМ матом/угрозами В АДРЕС МАГАЗИНА (не просто "блин", "ад", "жесть")
- Заказ в статусе "processing" (В обработке) и клиент хочет изменить/отменить
- Гарантия, возврат денег, обмен, рекламация — ты не можешь это решить
- Вопрос о платёжных данных: реквизиты, счёт, перевод

НЕ вызывай handoff когда:
- Клиент просит изменить заказ в draft/confirmed статусе — ПОМОГИ САМ через add_item_to_order / remove_item_from_order!
- Клиент просит отменить draft заказ — используй cancel_order!
- Заказ shipped/delivered/cancelled и клиент хочет изменить — просто скажи "невозможно", БЕЗ оператора!
- Клиент спрашивает о статусе доставки (используй check_order_status!)
- Клиент выбирает товар (даже если долго)
- Клиент задаёт off-topic вопросы (просто отклоняй)
- Клиент торгуется ("Цены фиксированные")
- Клиент просто выражает эмоции ("ад", "блин", "ну ёмаё") — это НЕ повод для handoff
- Клиент расстроен твоей ошибкой — извинись и исправь

При handoff скажи: "Подключаю оператора, подождите немного 🙏"

ПОВТОРНЫЙ КЛИЕНТ — "ОЛДИНГИ АДРЕС" / "ПРЕДЫДУЩИЙ АДРЕС":
- Если клиент говорит "олдинги адрессга жунатинг", "предыдущий адрес", "тот же адрес", "как прошлый раз", "как раньше" → вызови get_customer_history.
- Если tool вернул found=true → покажи данные и СПРОСИ подтверждение:
  Пример: "Прошлый заказ был на имя [имя], тел: [тел], адрес: [адрес]. Отправляем туда же?"
- Если клиент подтвердил ("да", "ха", "шунга") → используй эти данные в create_order_draft.
- Если tool вернул found=false → спроси данные как обычно.
- НЕ заставляй клиента повторять данные которые уже есть!

ДОСТАВКА — КРИТИЧЕСКИ ВАЖНО:
- Стоимость доставки бери ТОЛЬКО из результата tool (get_delivery_options или create_order_draft).
- ПЕРЕД create_order_draft ОБЯЗАТЕЛЬНО вызови get_delivery_options для города клиента!
- Если get_delivery_options вернул found=false → СРАЗУ скажи что в этот город доставка недоступна. Покажи available_cities.
- Если get_delivery_options вернул 1 вариант → НЕ спрашивай "курьер или самовывоз?". Просто скажи стоимость и срок.
- Если get_delivery_options вернул 2+ варианта → покажи ВСЕ и спроси какой выбирает.
- Если delivery_cost > 0 → покажи стоимость доставки ОТДЕЛЬНОЙ строкой.
- НИКОГДА не говори "доставка бесплатно" от себя — только если tool подтвердил.
- НИКОГДА не предлагай "самовывоз" если его нет в результатах get_delivery_options.

ГОРОД ИЗ АДРЕСА — КРИТИЧЕСКИ ВАЖНО:
- Клиент может указать РАЙОН/АДРЕС без явного города: "чилонзор ясси кучаси 39 дом", "юнусабад 4 квартал"
- Если в адресе есть название района Ташкента (Чиланзар, Юнусабад, Мирабад, Сергели и т.д.) → город = Ташкент. Вызови get_delivery_options("Ташкент").
- Если в адресе НЕ понятен город → ОБЯЗАТЕЛЬНО СПРОСИ: "В какой город доставка?"
- НЕ создавай заказ без определённого города! Без города → нет цены доставки.
- Доступные города: Ташкент, Самарканд, Бухара, Фергана, Наманган, Андижан, Нукус, Карши, Навои, Джизак, Ургенч, Термез.
- Если клиент назвал город которого нет в списке → get_delivery_options вернёт available_cities, покажи их.

══════ РЕКОМЕНДАЦИИ ══════
- "Какой посоветуете?", "Что лучше?", "До 15 млн?", "Для игр что есть?" → помоги выбрать.
- Сначала уточни: бюджет, для чего, что важно.
- Найди товары через get_product_candidates, потом get_variant_candidates.
- Покажи 2-3 лучших варианта, кратко объясни разницу.
- "Для игр — Legion 5. Для работы и автономности — MacBook. Что важнее?"
- Рекомендуй ТОЛЬКО из ассортимента, ТОЛЬКО по данным из tools.
- Не давай абстрактных советов — конкретные товары с ценами.

══════ ТОВАР НЕТ В НАЛИЧИИ — АЛЬТЕРНАТИВЫ ══════
КРИТИЧЕСКИ ВАЖНО: Когда товар out_of_stock — предлагай альтернативы из ТОЙ ЖЕ КАТЕГОРИИ!
- get_product_candidates возвращает category для каждого товара и suggestion с названием категории
- AirPods нет → ищи get_product_candidates("Аудио") — покажи ТОЛЬКО наушники, НЕ колонки!
- MacBook нет → ищи get_product_candidates("Ноутбуки")
- Если клиент хотел НАУШНИКИ — НЕ предлагай телефоны, колонки, планшеты!
- Смотри на название товара: "headphones", "наушники", "quloqchin" — это наушники. "колонка", "speaker" — это колонка. НЕ путай!

══════ НЕОДНОЗНАЧНОСТЬ ══════
ПРАВИЛО: При ЛЮБОЙ неоднозначности — УТОЧНЯЙ. Не угадывай!
- "четвёртый макбук" а 4-й ≠ MacBook → "Уточните: 4-й из списка или MacBook?"
- "этот" но показано несколько → "Какой именно?"
- Цвет которого нет → "Такого цвета нет. Есть: ... Какой?"
- Противоречивый ответ → переспроси вежливо.

ОПЕЧАТКИ И НЕПОНЯТНЫЕ ЗАПРОСЫ:
- Если клиент написал слово которое ПОХОЖЕ на товар но не совсем точно (например "афон", "ноут", "тливзор", "плншет") → НЕ гадай! Предложи ближайшие варианты:
  Пример: "афон" → "Вы имели в виду: 📱 Айфон (телефон) или 🎧 Наушники (AirPods)? Уточните, пожалуйста"
  Пример: "тливзор" → "Вы имели в виду телевизор? Могу показать варианты 👍"
- Если get_product_candidates вернул found=false → НЕ угадывай что клиент имел в виду! Спроси: "К сожалению, не нашёл '[запрос]'. Что именно вы ищете?"
- Если get_product_candidates вернул товары ДРУГОЙ категории чем ожидается → уточни. Например клиент написал "афон" → нашлись наушники, но может он имел в виду iPhone → спроси.

══════ МНОЖЕСТВЕННЫЕ ТОВАРЫ ══════
- "Хочу колонку и телевизор" → найди ВСЕ, покажи, добавь каждый.
- Один вариант → select_for_cart сразу. Несколько → спроси какой.
- НЕ показывай товар "в корзине" без вызова select_for_cart!

══════ ПРОАКТИВНЫЕ ПРЕДЛОЖЕНИЯ ══════
- После показа товара/цены: предложи "Добавить в корзину?"
- Если клиент оформляет заказ а ранее интересовался другим товаром → "Вы также смотрели [товар]. Добавить?"
- Если клиент проигнорировал → не повторяй больше одного раза.

ЗАПРЕЩЕНО:
- Придумывать цену, наличие, срок доставки, ХАРАКТЕРИСТИКИ (процессор, камера, экран, батарея, время работы и т.д.)
- Отвечать на вопросы о батарее/времени работы/процессоре/камере БЕЗ данных от tools — скажи "Для подробных характеристик подключу оператора"
- Говорить "добавил в корзину" если ты НЕ вызвал select_for_cart
- Говорить "нет в наличии" без проверки через tools
- Говорить "одну секунду", "подождите" — просто делай
- Говорить "к сожалению" + утверждение БЕЗ вызова tool — сначала проверь
- Добавлять фразы-заглушки после ответа ("дайте знать", "обращайтесь", "если интересно")
- Отвечать "я помогаю только с покупками" на вопросы О ПОКУПКЕ (цена, скидка, доставка, характеристики)
- Отвечать на вопросы не про магазин (наука, математика, советы, ремонт, жизнь)
- Добавлять товар в корзину БЕЗ явного выбора клиента
- Говорить "доставка бесплатно" если в delivery_note нет подтверждения
- Оформлять заказ без уточнения типа доставки (курьер/самовывоз)
- После add_item_to_order спрашивать адрес/имя/телефон — заказ УЖЕ существует, данные УЖЕ в нём!
- После add_item_to_order предлагать "оформить заказ" — он уже оформлен!
- Указывать RAM/storage/характеристики без вызова get_variant_candidates — ты НЕ ЗНАЕШЬ их пока tool не вернул!
- Смешивать языки в одном ответе
- Угадывать при неоднозначности — УТОЧНЯЙ
"""

# State-specific prompt sections — injected based on conversation.state
STATE_PROMPTS = {
    "idle": """\
ТЕКУЩИЙ ЭТАП: Клиент только начал диалог или вернулся после паузы.
- Если приветствие — поприветствуй.
- Если сразу вопрос/запрос — помоги.""",

    "browsing": """\
ТЕКУЩИЙ ЭТАП: Клиент СМОТРИТ КАТАЛОГ / ищет товар.
- Клиент может отвечать цифрой — посмотри что было под этим номером в твоём предыдущем списке.
- Цифра после списка ТОВАРОВ → вызови get_variant_candidates для выбранного товара. ПОКАЖИ варианты и ОСТАНОВИСЬ. НЕ вызывай select_for_cart в этом же раунде! Жди пока клиент САМИ выберет вариант.
- КРИТИЧНО: после get_variant_candidates — ПОКАЖИ СПИСОК ВАРИАНТОВ и ЖДИ ответа клиента! НЕ добавляй в корзину автоматически!
- "да" / "ага" → скорее всего подтверждает интерес к обсуждаемому товару. Покажи варианты.
- "нет" / "не то" → предложи другие варианты или спроси что именно ищет.""",

    "selection": """\
ТЕКУЩИЙ ЭТАП: Клиент ВЫБИРАЕТ ВАРИАНТ конкретного товара (цвет, объём, размер).
- Цифра ("1", "2", "3") → выбор варианта из показанного списка. Найди variant_id в state_context и вызови select_for_cart.
- "этот", "первый", "чёрный", "128гб" → выбор конкретного варианта. Вызови select_for_cart.
- "да" → подтверждает текущий обсуждаемый вариант → select_for_cart.
- "нет" / "другой" → клиент хочет другой вариант, НЕ удаляй ничего из корзины.
- НЕ путай "нет, не этот вариант" с "убери из корзины".""",

    "cart": """\
ТЕКУЩИЙ ЭТАП: В корзине есть товары. Клиент решает — добавить ещё или оформить.

КРИТИЧЕСКИ ВАЖНО — ОБРАБОТКА "НЕТ":
- Ты спросил "Ещё что-то или оформляем?" и клиент ответил "нет" / "всё" / "хватит" / "больше ничего" → это значит "НИЧЕГО БОЛЬШЕ НЕ НАДО, ОФОРМЛЯЕМ". НЕ удаляй из корзины! Переходи к оформлению: "Отлично! Напишите имя, телефон и адрес доставки"
- "да" после "Ещё что-то?" → клиент хочет ДОБАВИТЬ ещё. Спроси что именно.
- "убери X" / "не надо X" / "удали X" → ТОЛЬКО тогда вызови remove_from_cart с конкретным товаром.
- "очисти корзину" / "начать заначо" → remove_from_cart с variant_id="all"

FLOW ПОКУПКИ:
1. После select_for_cart → "Добавил [название]! Ещё что-то или оформляем?"
2. Клиент: "оформляйте" / "всё" / "нет" / "заказать" → сначала ПОКАЖИ содержимое корзины, потом спроси данные:
   Пример: "В корзине: PS5 Slim — 8 450 000, AirPods Pro 2 — 3 290 000. Итого: 11 740 000 сум. Напишите имя, телефон, город и адрес"
3. Клиент: "добавьте ещё..." → помоги выбрать, потом снова "Ещё что-то или оформляем?"
4. Когда клиент указал город → вызови get_delivery_options:
   - Если tool вернул found=false → СРАЗУ скажи: "К сожалению, в этот город доставка пока недоступна" + покажи available_cities
   - Если вернулся ТОЛЬКО 1 вариант (например только курьер) → НЕ спрашивай "курьер или самовывоз?", просто скажи: "Доставка курьером — X сум, Y дней"
   - Если вернулось 2+ варианта (курьер И самовывоз) → покажи оба и спроси какой выбирает
5. Когда есть ВСЕ данные (имя, телефон, город, адрес) → create_order_draft
- НЕ спрашивай данные каждый раз после добавления — только когда клиент подтвердил
- ОБЯЗАТЕЛЬНО перечисли все товары из корзины перед оформлением чтобы клиент мог проверить
- НЕ спрашивай "курьер или самовывоз?" если для города есть только один вариант доставки

УДАЛЕНИЕ ИЗ КОРЗИНЫ:
- ТОЛЬКО по явной просьбе: "убери", "удали", "без этого", "не надо X"
- После удаления: покажи что осталось""",

    "checkout": """\
ТЕКУЩИЙ ЭТАП: Клиент ОФОРМЛЯЕТ ЗАКАЗ — собираем данные.
- Нужны: имя, телефон, город, адрес.
- Если город указан → ОБЯЗАТЕЛЬНО вызови get_delivery_options:
  * found=false → "Доставка в этот город недоступна. Доставляем в: [available_cities]"
  * 1 вариант → просто покажи стоимость, НЕ спрашивай тип
  * 2+ варианта → покажи все и спроси какой выбирает
- Если клиент дал АДРЕС но без явного города:
  * Район Ташкента (чиланзар/чилонзор, юнусабад, мирабад и т.д.) → город = Ташкент
  * Непонятный адрес → СПРОСИ "В какой город доставка?"
- ОБЯЗАТЕЛЬНО: определи город ДО вызова create_order_draft!
- Когда есть ВСЕ данные (имя, телефон, город, адрес) + доставка проверена → create_order_draft.
- "отмена" / "не хочу" / "передумал" → вернись к корзине, товары остаются.""",

    "post_order": """\
ТЕКУЩИЙ ЭТАП: У клиента ЕСТЬ заказ(ы). Он может спрашивать о статусе, хотеть изменить/отменить.

СТАТУС ЗАКАЗА:
- "где мой заказ?", "статус", "когда доставка" → check_order_status
- Если клиент дал номер (ORD-XXXXX) → передай его в check_order_status
- Если нет номера → tool найдёт по telegram_user_id

ИЗМЕНЕНИЕ/ОТМЕНА ЗАКАЗА:
ВАЖНО: "хочу изменить/отменить заказ" — это НЕ агрессия! Это обычный запрос.
1. Сначала вызови check_order_status чтобы узнать РЕАЛЬНЫЙ статус
2. Tool вернёт allowed_actions — посмотри что можно:

ОТМЕНА:
   - cancel в allowed_actions + needs_operator=false → вызови cancel_order
   - cancel в allowed_actions + needs_operator=true → request_handoff("Клиент хочет отменить подтверждённый заказ")
   - cancel НЕ в allowed_actions → "Заказ уже отправлен/доставлен, отмена невозможна" (БЕЗ оператора!)

ИЗМЕНЕНИЕ (добавить/убрать товар):
   - edit в allowed_actions (статус draft/confirmed) → AI сам помогает! Спроси что хочет изменить:
     * "добавить товар" → найди товар через get_product_candidates → get_variant_candidates → СПРОСИ КАКОЙ ВАРИАНТ → add_item_to_order
     * КРИТИЧНО: если клиент сказал "кушин" / "добавь" / "добавить" после показа товаров → это ЗАПРОС ДОБАВИТЬ В ЗАКАЗ! Не показывай просто список — ДОБАВЬ через add_item_to_order!
     * Если показал варианты и клиент выбрал (номер / "4к" / "тот") → СРАЗУ add_item_to_order с variant_id, НЕ показывай ещё раз!
     * "убрать товар" → remove_item_from_order
     * "изменить цену" / "скидка" → "Цены фиксированные, не могу изменить цену. Но могу добавить/убрать товары из заказа"
   - edit_via_operator в allowed_actions (статус processing) → request_handoff("Клиент хочет изменить заказ в обработке")
   - edit НЕ в allowed_actions (shipped/delivered/cancelled) → "Заказ уже отправлен/доставлен/отменён, изменения невозможны" (БЕЗ оператора! Категорический отказ)

3. ВАЖНО: для shipped/delivered/cancelled — НЕ вызывай оператора! Просто скажи что изменить нельзя.
4. Оператора вызывай ТОЛЬКО для processing статуса.

ПОСЛЕ УСПЕШНОГО add_item_to_order / remove_item_from_order — СТРОГИЕ ПРАВИЛА:
- АБСОЛЮТНЫЙ ЗАПРЕТ: НЕ спрашивай адрес, имя, телефон, город! Заказ УЖЕ СУЩЕСТВУЕТ! Все данные УЖЕ в нём!
- АБСОЛЮТНЫЙ ЗАПРЕТ: НЕ говори "напишите адрес доставки", "оформить заказ", "если всё верно". Заказ УЖЕ оформлен!
- Ты просто ДОБАВИЛ/УБРАЛ товар из существующего заказа. Это как положить товар в сумку которая уже собрана.
- Отвечай ТОЛЬКО ТАК: "Добавил [товар] в заказ [номер]! Новая сумма: X сум 👍 Что-нибудь ещё?"
- Если клиент говорит "всё" / "спасибо" / "нет" → "Готово! Обращайтесь если что 👍"

ОБРАБОТКА "НЕТ" / "СПАСИБО" / "ВСЁ" В POST_ORDER:
- Если клиент отвечает "нет" / "всё" / "спасибо" / "спс" / "хватит" / "ок" после изменения заказа или после "Что-нибудь ещё?" → это КОНЕЦ РАЗГОВОРА. НЕ переходи к оформлению!
- Ответь КРАТКО и ДРУЖЕЛЮБНО: "Отлично! Ваш заказ обновлён 👍 Если что — обращайтесь!" или "Готово! Спасибо за покупку! 🙏"
- АБСОЛЮТНЫЙ ЗАПРЕТ: НЕ говори "Теперь оформляем", "Напишите адрес", "имя и телефон" — заказ УЖЕ СУЩЕСТВУЕТ!

ПОСЛЕДНИЕ ИЗМЕНЕНИЯ ЗАКАЗА:
Если в state_context есть last_order_modifications — это то что ты (AI) реально делал с заказом.
Если клиент спрашивает "ты добавил?" / "ты сделал?" — посмотри last_order_modifications и ответь ДА если там есть запись.

Клиент может ТАКЖЕ хотеть заказать новый товар — это нормально. Помоги как обычно.""",

    "handoff": """\
ТЕКУЩИЙ ЭТАП: Диалог ПЕРЕДАН ОПЕРАТОРУ. AI отключен.""",
}


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_categories",
            "description": "List all product categories with product counts. Use when customer asks 'what do you have?', 'что есть?', 'что продаёте?'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_candidates",
            "description": "Search products by name, alias, or variant title. Returns matching products with product_id, total_available_stock, price_range, in_stock. IMPORTANT: if in_stock=false, do NOT recommend this product — it is out of stock.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query — product name, alias, or category"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_variant_candidates",
            "description": "Get all variants for a product with title, color, storage, ram, size, price, stock, and specs (processor, display, camera, battery, etc. if available). Returns variant_id UUIDs needed for ordering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "Product UUID from get_product_candidates or state_context"},
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_variant_price",
            "description": "Get exact price for a specific variant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variant_id": {"type": "string", "description": "Variant UUID"},
                },
                "required": ["variant_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_variant_stock",
            "description": "Get stock for a specific variant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variant_id": {"type": "string", "description": "Variant UUID"},
                },
                "required": ["variant_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_delivery_options",
            "description": "Get delivery options for a city. Supports Russian/English/Uzbek city names.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name in any language"},
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_for_cart",
            "description": "Add a variant to the customer's cart. Call this when customer picks a specific variant (says '2', 'чёрный', 'этот'). Gets variant_id from state_context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variant_id": {"type": "string", "description": "Variant UUID from state_context"},
                    "qty": {"type": "integer", "description": "Quantity (default 1)"},
                },
                "required": ["variant_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Remove a specific item from cart. ONLY call when customer EXPLICITLY says 'убери X', 'удали X', 'не надо X', 'без X'. Do NOT call when customer says 'нет' to 'ещё что-то?' — that means proceed to checkout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variant_id": {"type": "string", "description": "Variant UUID to remove. Use 'all' to clear entire cart."},
                },
                "required": ["variant_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order_draft",
            "description": "Create order from items in cart. Cart must have items (use select_for_cart first). Reserves inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Customer full name"},
                    "phone": {"type": "string", "description": "Phone number"},
                    "city": {"type": "string", "description": "City"},
                    "address": {"type": "string", "description": "Delivery address"},
                },
                "required": ["customer_name", "phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_order_status",
            "description": "Check order status and allowed actions. Use when customer asks 'где мой заказ?', 'статус заказа', 'когда доставка', 'хочу изменить/отменить заказ'. Returns status + allowed_actions (cancel, edit, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string", "description": "Order number like ORD-XXXXX. Optional — if not provided, finds all orders for this user."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "Cancel an order. Works for draft orders (AI cancels directly). For confirmed orders, returns needs_operator=true. For processing/shipped/delivered — cancellation impossible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string", "description": "Order number like ORD-XXXXX"},
                },
                "required": ["order_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_item_to_order",
            "description": "Add a product variant to an existing order (draft/confirmed only). Use when customer wants to add a product to their order. First find the variant via get_product_candidates + get_variant_candidates, then call this.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string", "description": "Order number like ORD-XXXXX or just XXXXX (ORD- prefix added automatically)"},
                    "variant_id": {"type": "string", "description": "Variant UUID to add"},
                    "qty": {"type": "integer", "description": "Quantity (default 1)"},
                },
                "required": ["order_number", "variant_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_item_from_order",
            "description": "Remove a product (or reduce its quantity) from an existing order (draft/confirmed only). Use when customer asks to remove an item OR reduce quantity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string", "description": "Order number like ORD-XXXXX"},
                    "variant_id": {"type": "string", "description": "Variant UUID to remove"},
                    "qty": {"type": "integer", "description": "How many to remove. If omitted or >= current qty, removes entirely. If < current qty, reduces quantity."},
                },
                "required": ["order_number", "variant_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_history",
            "description": "Get returning customer's previous delivery info (name, phone, city, address). Use when customer says 'send to previous address', 'олдинги адресс', 'тот же адрес', 'как прошлый раз'. Returns last order's delivery data for confirmation.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_handoff",
            "description": "Transfer conversation to a human operator. Use for: order edits on confirmed orders, returns/exchanges, payment questions, persistent conflicts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Reason for handoff — be specific (e.g. 'customer wants to edit confirmed order ORD-ABC123')"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "description": "Priority level. Default normal. Use high for order issues, urgent for angry customers."},
                    "linked_order_number": {"type": "string", "description": "Order number if handoff is related to a specific order"},
                },
                "required": ["reason"],
            },
        },
    },
]


def _build_order_modification_response(tool_name: str, result: dict, language: str = "ru") -> str | None:
    """Build a deterministic response for order modification tools.

    Returns a ready-made response string, bypassing the LLM entirely.
    This prevents the LLM from asking for address/checkout after modifying an existing order.
    Language-aware: responds in the customer's language.
    """
    title = result.get("item_title", "?")
    order_num = result.get("order_number", "")
    new_total = result.get("new_total", "?")
    try:
        total_fmt = f"{int(float(new_total)):,}".replace(",", " ")
    except (ValueError, TypeError):
        total_fmt = str(new_total)

    if tool_name == "add_item_to_order" and result.get("success"):
        if result.get("action") == "quantity_updated":
            new_qty = result.get("new_qty", "?")
            templates = {
                "ru": f"Обновил количество {title} в заказе {order_num} — теперь {new_qty} шт. Общая сумма: {total_fmt} сум 👍 Яна нима керак бўлса, ёзинг!",
                "uz_cyrillic": f"{title} миқдори {order_num} буюртмада янгиланди — энди {new_qty} дона. Жами: {total_fmt} сўм 👍 Яна нима керак бўлса, ёзинг!",
                "uz_latin": f"{title} miqdori {order_num} buyurtmada yangilandi — endi {new_qty} dona. Jami: {total_fmt} so'm 👍 Yana nima kerak bo'lsa, yozing!",
                "en": f"Updated {title} quantity in order {order_num} — now {new_qty} pcs. Total: {total_fmt} UZS 👍 Let me know if you need anything else!",
            }
        else:
            templates = {
                "ru": f"Добавил {title} в заказ {order_num}! Общая сумма: {total_fmt} сум 👍 Ещё что-то нужно?",
                "uz_cyrillic": f"{title} {order_num} буюртмага қўшилди! Жами: {total_fmt} сўм 👍 Яна нима керак бўлса, ёзинг!",
                "uz_latin": f"{title} {order_num} buyurtmaga qo'shildi! Jami: {total_fmt} so'm 👍 Yana nima kerak bo'lsa, yozing!",
                "en": f"Added {title} to order {order_num}! Total: {total_fmt} UZS 👍 Need anything else?",
            }
        return templates.get(language, templates["ru"])

    if tool_name == "remove_item_from_order" and result.get("success"):
        removed = result.get("removed_item", result.get("item_title", "?"))
        remaining = result.get("remaining_items", "?")
        if result.get("action") == "quantity_reduced":
            rem_qty = result.get("remaining_qty", "?")
            templates = {
                "ru": f"Уменьшил количество {removed} в заказе {order_num} — осталось {rem_qty} шт. Сумма: {total_fmt} сум. Ещё что-то?",
                "uz_cyrillic": f"{removed} миқдори {order_num} буюртмада камайтирилди — {rem_qty} дона қолди. Жами: {total_fmt} сўм. Яна нима керак?",
                "uz_latin": f"{removed} miqdori {order_num} buyurtmada kamaytirildi — {rem_qty} dona qoldi. Jami: {total_fmt} so'm. Yana nima kerak?",
                "en": f"Reduced {removed} quantity in order {order_num} — {rem_qty} left. Total: {total_fmt} UZS. Anything else?",
            }
        else:
            templates = {
                "ru": f"Убрал {removed} из заказа {order_num}. Осталось {remaining} товаров, сумма: {total_fmt} сум. Ещё что-то?",
                "uz_cyrillic": f"{removed} {order_num} буюртмадан олиб ташланди. {remaining} та товар қолди, жами: {total_fmt} сўм. Яна нима керак?",
                "uz_latin": f"{removed} {order_num} buyurtmadan olib tashlandi. {remaining} ta tovar qoldi, jami: {total_fmt} so'm. Yana nima kerak?",
                "en": f"Removed {removed} from order {order_num}. {remaining} items left, total: {total_fmt} UZS. Anything else?",
            }
        return templates.get(language, templates["ru"])

    # Forced response for create_order_draft — ALWAYS show order number + real items
    if tool_name == "create_order_draft" and result.get("order_id"):
        order_num = result.get("order_number", "?")
        items = result.get("items", [])
        total = result.get("total_amount", "?")
        delivery = result.get("delivery_note", "")
        eta = result.get("delivery_eta", "")

        try:
            total_fmt = f"{int(float(total)):,}".replace(",", " ")
        except (ValueError, TypeError):
            total_fmt = str(total)

        items_lines = []
        for item in items:
            ititle = item.get("title", "?")
            iprice = item.get("total_price", item.get("unit_price", "?"))
            try:
                iprice_fmt = f"{int(float(iprice)):,}".replace(",", " ")
            except (ValueError, TypeError):
                iprice_fmt = str(iprice)
            qty = item.get("qty", 1)
            qty_str = f" x{qty}" if qty > 1 else ""
            items_lines.append(f"  - {ititle}{qty_str} — {iprice_fmt}")

        items_text = "\n".join(items_lines)
        delivery_line = f"\n  - Доставка: {delivery}" if delivery else ""
        eta_line = f"\nСрок: {eta}" if eta else ""

        if language == "en":
            return (
                f"Order confirmed! 🎉\n\n"
                f"Order number: {order_num}\n"
                f"Items:\n{items_text}{delivery_line}\n\n"
                f"Total: {total_fmt} UZS{eta_line}\n\n"
                f"Thank you for your purchase! If you need anything, just write!"
            )
        elif language == "uz_cyrillic":
            return (
                f"Буюртма расмийлаштирилди! 🎉\n\n"
                f"Буюртма рақами: {order_num}\n"
                f"Товарлар:\n{items_text}{delivery_line}\n\n"
                f"Жами: {total_fmt} сўм{eta_line}\n\n"
                f"Харидингиз учун раҳмат! Яна нима керак бўлса, ёзинг!"
            )
        elif language == "uz_latin":
            return (
                f"Buyurtma rasmiylashtirildi! 🎉\n\n"
                f"Buyurtma raqami: {order_num}\n"
                f"Tovarlar:\n{items_text}{delivery_line}\n\n"
                f"Jami: {total_fmt} so'm{eta_line}\n\n"
                f"Xaridingiz uchun rahmat! Yana nima kerak bo'lsa, yozing!"
            )
        else:  # ru
            return (
                f"Заказ оформлен! 🎉\n\n"
                f"Номер заказа: {order_num}\n"
                f"Товары:\n{items_text}{delivery_line}\n\n"
                f"Итого: {total_fmt} сум{eta_line}\n\n"
                f"Спасибо за покупку! Если что — пишите!"
            )

    return None


def _build_context_summary(state_context: dict | None) -> str:
    """Build a summary of known products/variants from state_context for the system prompt."""
    if not state_context:
        return ""

    parts = []

    # Cart (most important — these will be ordered)
    cart = state_context.get("cart", [])
    if cart:
        try:
            total = sum(float(item.get("price", 0)) * int(item.get("qty", 1)) for item in cart)
            total_fmt = f"{int(total):,}".replace(",", " ")
        except (ValueError, TypeError):
            total_fmt = "?"
        parts.append("═══ РЕАЛЬНАЯ КОРЗИНА КЛИЕНТА (ТОЛЬКО ЭТИ ТОВАРЫ!) ═══")
        parts.append(f"⚠️ ВАЖНО: В корзине ровно {len(cart)} товар(ов). НЕ добавляй другие товары в список при оформлении!")
        for i, item in enumerate(cart, 1):
            title = item.get("title", "?")
            price = item.get("price", "?")
            qty = item.get("qty", 1)
            vid = item.get("variant_id", "?")
            try:
                price_fmt = f"{int(float(price)):,}".replace(",", " ")
            except (ValueError, TypeError):
                price_fmt = str(price)
            parts.append(f"  {i}. {title} — {price_fmt} сум x{qty} (variant_id: {vid})")
        parts.append(f"  Итого товаров: {total_fmt} сум")
        parts.append("═══════════════════════════════════════════════")
        parts.append("")

    # Known products from search
    products = state_context.get("products", {})
    if products:
        parts.append("Известные товары в этом диалоге:")
        for name, info in products.items():
            pid = info.get("product_id", "?")
            parts.append(f"  {name} (product_id: {pid})")
            for i, v in enumerate(info.get("variants", []), 1):
                vid = v.get("variant_id", "?")
                title = v.get("title", "?")
                price = v.get("price", "?")
                stock = v.get("available_quantity", "?")
                specs = v.get("specs")
                spec_str = ""
                if specs and isinstance(specs, dict):
                    spec_parts = [f"{k}: {val}" for k, val in specs.items()]
                    spec_str = f" | {', '.join(spec_parts)}"
                parts.append(f"    {i}. {title} — {price} сум, {stock} шт (variant_id: {vid}){spec_str}")

    # Proactive suggestion: products shown but not in cart
    shown = state_context.get("shown_products", [])
    if cart and shown:
        cart_vids = {item.get("variant_id") for item in cart}
        cart_pids = set()
        for item in cart:
            vid = item.get("variant_id")
            for prod_info in state_context.get("products", {}).values():
                for v in prod_info.get("variants", []):
                    if v.get("variant_id") == vid:
                        cart_pids.add(prod_info.get("product_id"))
        not_carted = [s for s in shown if s.get("variant_id") not in cart_vids and s.get("product_id") not in cart_pids]
        if not_carted:
            parts.append("ТОВАРЫ КОТОРЫЕ КЛИЕНТ СМОТРЕЛ НО НЕ ДОБАВИЛ В КОРЗИНУ:")
            for s in not_carted[-3:]:  # Last 3 at most
                parts.append(f"  → {s.get('title', '?')} — {s.get('price', '?')} сум")
            parts.append("  💡 Когда клиент переходит к оформлению — ОДИН раз спроси: 'Вы также смотрели [товар]. Добавить в заказ?' Если игнорирует — не повторяй.")
            parts.append("")

    # Previous orders
    orders = state_context.get("orders", [])
    if orders:
        parts.append("\nЗаказы клиента:")
        for o in orders:
            parts.append(f"  {o.get('order_number', '?')} — {o.get('total_amount', '?')} сум")

    customer = state_context.get("customer", {})
    if customer:
        parts.append(f"\nДанные клиента: имя={customer.get('name','?')}, тел={customer.get('phone','?')}, город={customer.get('city','?')}, адрес={customer.get('address','?')}")

    # Recent order modifications (what AI actually did)
    mods = state_context.get("last_order_modifications", [])
    if mods:
        parts.append("\nПОСЛЕДНИЕ ИЗМЕНЕНИЯ ЗАКАЗОВ (ты это сделал!):")
        for m in mods:
            action = "Добавил" if m.get("action") == "added" else "Убрал"
            parts.append(f"  ✓ {action} {m.get('item', '?')} в заказ {m.get('order', '?')}")

    return "\n".join(parts) if parts else ""


def _determine_state(conversation: Conversation, state_context: dict) -> str:
    """Determine the current conversation state based on data."""
    # If explicitly set and valid, use it
    current = conversation.state or "idle"

    # Auto-detect based on state_context
    cart = state_context.get("cart", [])
    orders = state_context.get("orders", [])
    products = state_context.get("products", {})

    if current == "handoff":
        return "handoff"

    # Has orders → post_order (unless actively shopping again)
    if orders and not cart and current not in ("browsing", "selection"):
        return "post_order"

    # Has cart items
    if cart:
        return "cart"

    # Has products with variants loaded → selection
    for info in products.values():
        if info.get("variants"):
            return "selection"

    # Has products without variants → browsing
    if products:
        return "browsing"

    # Default
    if current in ("idle", "NEW_CHAT"):
        return "idle"

    return current


def _update_context_from_tool(state_context: dict, tool_name: str, tool_args: dict, tool_result: dict) -> dict:
    """Update state_context with data from tool results."""
    if tool_name == "get_product_candidates" and tool_result.get("found"):
        products = state_context.setdefault("products", {})
        result_products = tool_result.get("products", [])
        # Track shown products for proactive suggestions — BUT only for SPECIFIC searches
        # (1-2 results). Category listings (3+ results) are too broad — user didn't
        # specifically ask about any of those products.
        shown = state_context.setdefault("shown_products", [])
        in_stock_results = [p for p in result_products if p.get("in_stock", True) and p.get("total_available_stock", 0) > 0]
        is_specific_search = len(in_stock_results) <= 2
        for p in result_products:
            products[p["name"]] = {
                "product_id": p["product_id"],
                "brand": p.get("brand"),
                "model": p.get("model"),
                "total_available_stock": p.get("total_available_stock", 0),
                "in_stock": p.get("in_stock", True),
                "price_range": p.get("price_range"),
                "variants": [],
            }
            # Only track for proactive suggestion if this was a specific search (1-2 results)
            if is_specific_search and p.get("in_stock", True) and p.get("total_available_stock", 0) > 0:
                pid = p["product_id"]
                price_range = p.get("price_range", "?")
                if not any(s.get("product_id") == pid for s in shown):
                    shown.append({
                        "product_id": pid,
                        "title": p["name"],
                        "price": price_range,
                    })
        # Keep only last 10
        if len(shown) > 10:
            state_context["shown_products"] = shown[-10:]

    elif tool_name == "get_variant_candidates" and tool_result.get("found"):
        variants = tool_result.get("variants", [])
        if variants:
            products = state_context.get("products", {})
            called_pid = tool_args.get("product_id", "")
            matched = False
            for name, info in products.items():
                if info.get("product_id") == called_pid:
                    info["variants"] = variants
                    matched = True
                    break
            if not matched:
                first_title = variants[0].get("title", "Unknown")
                state_context.setdefault("products", {})[first_title] = {
                    "product_id": called_pid,
                    "variants": variants,
                }

            # Track shown products for proactive suggestions later
            shown = state_context.setdefault("shown_products", [])
            for v in variants:
                vid = v.get("variant_id")
                title = v.get("title", "?")
                price = v.get("price", "?")
                if vid and not any(s.get("variant_id") == vid for s in shown):
                    shown.append({"variant_id": vid, "title": title, "price": price})
            # Keep only last 10 shown
            if len(shown) > 10:
                state_context["shown_products"] = shown[-10:]

    elif tool_name in ("select_for_cart", "remove_from_cart"):
        if tool_result.get("cart") is not None:
            state_context["cart"] = tool_result["cart"]

    elif tool_name == "create_order_draft" and tool_result.get("order_id"):
        orders = state_context.setdefault("orders", [])
        orders.append({
            "order_id": tool_result["order_id"],
            "order_number": tool_result.get("order_number"),
            "total_amount": tool_result.get("total_amount"),
            "items": tool_result.get("items", []),
        })

    elif tool_name == "cancel_order" and tool_result.get("cancelled"):
        # Remove cancelled order from context
        order_num = tool_result.get("order_number")
        orders = state_context.get("orders", [])
        state_context["orders"] = [o for o in orders if o.get("order_number") != order_num]

    elif tool_name in ("add_item_to_order", "remove_item_from_order") and tool_result.get("success"):
        # Update order total and items in context
        order_num = tool_result.get("order_number")
        new_total = tool_result.get("new_total")
        if order_num and new_total:
            for o in state_context.get("orders", []):
                if o.get("order_number") == order_num:
                    o["total_amount"] = new_total
                    # Update items list in context
                    if tool_name == "add_item_to_order":
                        items = o.setdefault("items", [])
                        items.append({
                            "title": tool_result.get("item_title", "?"),
                            "qty": tool_result.get("qty", 1),
                            "unit_price": tool_result.get("item_price", "0"),
                            "total_price": tool_result.get("item_price", "0"),
                        })
                    elif tool_name == "remove_item_from_order":
                        removed_title = tool_result.get("removed_item", tool_result.get("item_title", ""))
                        action = tool_result.get("action")
                        items = o.get("items", [])
                        if action == "quantity_reduced":
                            # Update qty for reduced item
                            for it in items:
                                if it.get("title") == removed_title:
                                    it["qty"] = tool_result.get("remaining_qty", it["qty"])
                                    break
                        else:
                            # Full removal
                            o["items"] = [it for it in items if it.get("title") != removed_title]

        # Track modification history so AI remembers what it did
        mods = state_context.setdefault("last_order_modifications", [])
        if tool_name == "add_item_to_order":
            mods.append({
                "action": "added",
                "item": tool_result.get("item_title", "?"),
                "order": order_num,
                "new_total": new_total,
            })
        elif tool_name == "remove_item_from_order":
            mods.append({
                "action": tool_result.get("action", "removed"),
                "item": tool_result.get("removed_item", tool_result.get("item_title", "?")),
                "order": order_num,
                "new_total": new_total,
            })
        # Keep only last 5 modifications
        if len(mods) > 5:
            state_context["last_order_modifications"] = mods[-5:]

    return state_context


import re as _re

# Keywords that indicate order modification intent
_ORDER_MODIFY_KEYWORDS = [
    "изменить", "изменит", "измени", "изменю", "поменять", "поменяй",
    "добавить", "добавит", "добавь", "добавишь", "добавляй",
    "убрать", "убери", "удалить", "удали",
    "отменить", "отмени", "отменяй",
    "редактировать", "edit", "cancel",
]
_ORDER_STATUS_KEYWORDS = ["статус", "проверить", "проверь", "где мой", "когда доставка", "заказ"]
# Two patterns: with ORD prefix (always valid) and bare hex (must contain a letter a-f)
_ORDER_NUMBER_PATTERN_FULL = _re.compile(r'\bORD[- ]?([A-Fa-f0-9]{8})\b', _re.IGNORECASE)
_ORDER_NUMBER_PATTERN_BARE = _re.compile(r'\b([0-9]*[A-Fa-f][A-Fa-f0-9]*)\b')
# States where we should NOT try to detect order numbers (user is providing address/phone)
_ORDER_PREPROCESS_SKIP_STATES = {"cart", "checkout"}


async def _preprocess_order_request(
    tenant_id: UUID,
    conversation: Conversation,
    user_message: str,
    state_context: dict,
    db: AsyncSession,
) -> dict:
    """Pre-process user message to detect order numbers and handle deterministically.

    Returns:
        - {"forced_response": "..."} to skip LLM entirely
        - {"order_context_injection": "..."} to enrich LLM context
        - {} if no order detected
    """
    from src.orders.models import Order
    from src.leads.models import Lead
    from src.ai.policies import AI_EDITABLE_STATUSES, LOCKED_STATUSES, STATUS_LABELS_RU
    from src.ai.truth_tools import _normalize_order_number
    from sqlalchemy.orm import selectinload

    text_lower = user_message.lower()

    # Skip order detection in cart/checkout state — user is providing address/phone, not order numbers
    current_conv_state = conversation.state or "idle"
    if current_conv_state in _ORDER_PREPROCESS_SKIP_STATES:
        return {}

    # Extract order numbers — first try with ORD prefix (always reliable)
    full_matches = _ORDER_NUMBER_PATTERN_FULL.findall(user_message)
    if full_matches:
        raw_order_num = full_matches[0]
    else:
        # Bare hex — must contain at least one letter [a-f] to avoid matching phone numbers
        # AND message must have order-related keywords
        has_order_intent = any(kw in text_lower for kw in _ORDER_MODIFY_KEYWORDS + _ORDER_STATUS_KEYWORDS)
        if not has_order_intent:
            return {}
        bare_matches = _ORDER_NUMBER_PATTERN_BARE.findall(user_message)
        # Filter: exactly 8 hex chars and at least one letter
        valid_bare = [m for m in bare_matches if len(m) == 8 and any(c in 'abcdefABCDEF' for c in m)]
        if not valid_bare:
            return {}
        raw_order_num = valid_bare[0]

    order_number = _normalize_order_number(raw_order_num)

    # Look up order
    order_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.order_number == order_number,
        ).options(selectinload(Order.items))
    )
    order = order_result.scalar_one_or_none()

    if not order:
        return {"forced_response": f"Заказ с номером {raw_order_num} не найден. Проверьте номер и попробуйте снова."}

    # Check ownership
    if order.lead_id:
        lead_result = await db.execute(select(Lead).where(Lead.id == order.lead_id))
        lead = lead_result.scalar_one_or_none()
        if lead and lead.telegram_user_id != conversation.telegram_user_id:
            return {"forced_response": f"Заказ с номером {raw_order_num} не найден. Проверьте номер и попробуйте снова."}

    # Determine intent
    is_modify = any(kw in text_lower for kw in _ORDER_MODIFY_KEYWORDS)
    is_status_check = any(kw in text_lower for kw in _ORDER_STATUS_KEYWORDS)

    status = order.status
    status_label = STATUS_LABELS_RU.get(status, status)

    # Build items list
    items_lines = []
    from src.catalog.models import ProductVariant
    for item in order.items:
        title = "?"
        if item.product_variant_id:
            v_result = await db.execute(
                select(ProductVariant).where(ProductVariant.id == item.product_variant_id)
            )
            v = v_result.scalar_one_or_none()
            if v:
                title = v.title
        try:
            price_fmt = f"{int(item.total_price):,}".replace(",", " ")
        except (ValueError, TypeError):
            price_fmt = str(item.total_price)
        items_lines.append(f"- {title} x{item.qty} — {price_fmt} сум")

    items_text = "\n".join(items_lines) if items_lines else "Нет товаров"
    try:
        total_fmt = f"{int(order.total_amount):,}".replace(",", " ")
    except (ValueError, TypeError):
        total_fmt = str(order.total_amount)

    # --- Handle modification requests deterministically ---
    if is_modify:
        if status in LOCKED_STATUSES:
            # shipped/delivered/cancelled → flat refusal, no operator
            return {
                "forced_response": f"Заказ {order.order_number} в статусе \"{status_label}\" — изменения невозможны. Могу помочь с чем-то другим!"
            }

        if status == "processing":
            # Need operator — create handoff
            from src.handoffs.models import Handoff
            handoff = Handoff(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                reason=f"Клиент хочет изменить заказ {order.order_number} (в обработке)",
                priority="high",
                summary=f"Заказ {order.order_number} на сумму {total_fmt} сум в обработке, клиент хочет изменить",
                linked_order_id=order.id,
            )
            db.add(handoff)
            conversation.status = "handoff"
            conversation.ai_enabled = False
            return {
                "forced_response": f"Заказ {order.order_number} сейчас в обработке. Для изменений подключу оператора, подождите немного 🙏"
            }

        if status in AI_EDITABLE_STATUSES:
            # AI can help — inject order info for LLM
            order_info = (
                f"Заказ {order.order_number} — статус: {status_label}\n"
                f"Товары в заказе:\n{items_text}\n"
                f"Итого: {total_fmt} сум\n"
                f"СТАТУС ПОЗВОЛЯЕТ ИЗМЕНЕНИЕ! Используй add_item_to_order / remove_item_from_order для этого заказа.\n"
                f"НЕ вызывай request_handoff — ты МОЖЕШЬ изменить этот заказ сам!"
            )
            return {"order_context_injection": order_info}

    # --- Handle status check ---
    if is_status_check or not is_modify:
        # Just show order info — inject into context for LLM
        order_info = (
            f"Заказ {order.order_number} — статус: {status_label}\n"
            f"Товары:\n{items_text}\n"
            f"Итого: {total_fmt} сум"
        )
        if status in AI_EDITABLE_STATUSES:
            order_info += "\nСтатус позволяет изменение (add_item_to_order / remove_item_from_order)."
        elif status in LOCKED_STATUSES:
            order_info += f"\nСтатус \"{status_label}\" — изменения НЕВОЗМОЖНЫ."
        return {"order_context_injection": order_info}

    return {}


async def process_dm_message(
    tenant_id: UUID,
    conversation_id: UUID,
    user_message: str,
    db: AsyncSession,
) -> str | None:
    """Process an incoming DM and generate AI response."""
    try:
        import openai

        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

        # --- Step 1: Load conversation and state_context ---
        conv_result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            logger.error("Conversation %s not found", conversation_id)
            return None

        state_context = copy.deepcopy(conversation.state_context) if conversation.state_context else {}

        # --- Step 1.1: Detect language ---
        current_lang = state_context.get("language", "ru")
        detected_lang = _detect_language(user_message, current_lang)
        state_context["language"] = detected_lang

        # --- Step 1.2: Deterministic greeting handler ---
        # Fire for ALL states — if user says "привет" in post_order state, they're greeting
        # and should get a deterministic response in the correct language.
        current_conv_state = conversation.state or "idle"
        greeting_response = _check_greeting(user_message, detected_lang)
        if greeting_response:
            # Reset to idle on greeting (user is starting fresh or re-engaging)
            if current_conv_state not in ("idle", "NEW_CHAT"):
                conversation.state = "idle"
            conversation.state_context = state_context
            flag_modified(conversation, "state_context")
            await db.flush()
            return greeting_response

        # --- Step 1.3: Proactive suggestion at checkout transition ---
        # When user says "оформляем"/"го"/"всё" and there are products they viewed but didn't add,
        # suggest them ONE TIME before proceeding to checkout.
        cart = state_context.get("cart", [])
        shown = state_context.get("shown_products", [])
        _checkout_triggers = {
            # Russian
            "оформляем", "оформить", "оформи", "го", "давай", "всё", "вроде все",
            "вроде всё", "хватит", "больше ничего", "заказать", "заказ",
            # Affirmative responses (user says "да" after AI asks "Оформляем?")
            "да", "ок", "окей", "ага", "угу", "конечно", "ладно", "хорошо",
            # English affirmative
            "yes", "yeah", "yep", "sure", "ok", "okay", "done",
            # Uzbek affirmative
            "ха", "хоп", "хўп", "майли", "шундай", "ha", "hop", "xop", "mayli",
            # English checkout
            "checkout", "check out", "proceed", "order", "that's all", "thats all",
            "nothing else", "go checkout", "go to checkout", "place order",
            # Uzbek checkout
            "rasmiylashtiramiz", "buyurtma", "расмийлаштирамиз", "буюртма",
            "тамом", "бас", "бўлди", "tamom", "bas", "boldi",
        }
        msg_lower_stripped = user_message.strip().lower().rstrip("!?.,")
        _is_checkout_trigger = (
            current_conv_state == "cart"
            and any(t in msg_lower_stripped for t in _checkout_triggers)
        )
        # Debug logging for proactive suggestion
        logger.info(
            "PROACTIVE CHECK: state=%s, msg=%r, is_trigger=%s, cart=%d items, shown=%d items, suggested=%s",
            current_conv_state, msg_lower_stripped, _is_checkout_trigger,
            len(cart), len(shown), state_context.get("_proactive_suggested", False),
        )
        if _is_checkout_trigger and cart and shown:
            # Build set of product_ids and variant_ids that are in cart
            cart_vids = {item.get("variant_id") for item in cart}
            cart_pids = set()
            for item in cart:
                # Resolve product_id from variant in known products
                vid = item.get("variant_id")
                for prod_info in state_context.get("products", {}).values():
                    for v in prod_info.get("variants", []):
                        if v.get("variant_id") == vid:
                            cart_pids.add(prod_info.get("product_id"))
            # Filter shown items: exclude those already in cart (by variant_id or product_id)
            not_added = [
                s for s in shown
                if s.get("variant_id") not in cart_vids
                and s.get("product_id") not in cart_pids
            ]
            # Only suggest once — check flag in state_context
            already_suggested = state_context.get("_proactive_suggested", False)
            logger.info(
                "PROACTIVE FILTER: cart_vids=%s, cart_pids=%s, not_added=%s, already_suggested=%s, shown_raw=%s",
                cart_vids, cart_pids, [s.get("title") for s in not_added],
                already_suggested, [s.get("title") for s in shown],
            )
            if not_added and not already_suggested:
                state_context["_proactive_suggested"] = True
                # Build suggestion in detected language
                items_text = ", ".join(s.get("title", "?") for s in not_added[:2])
                suggestions = {
                    "ru": f"Кстати, вы ещё интересовались {items_text} — добавить в заказ? Если не нужно, скажите и оформляем 👍",
                    "uz_cyrillic": f"Айтганча, сиз {items_text} ҳам кўрган эдингиз — буюртмага қўшайми? Керак бўлмаса, айтинг, расмийлаштирамиз 👍",
                    "uz_latin": f"Aytgancha, siz {items_text} ham ko'rgan edingiz — buyurtmaga qo'shaymi? Kerak bo'lmasa, ayting, rasmiylashtiramiz 👍",
                    "en": f"By the way, you were also looking at {items_text} — want to add it to your order? If not, just say and we'll proceed 👍",
                }
                conversation.state_context = state_context
                flag_modified(conversation, "state_context")
                await db.flush()
                return suggestions.get(detected_lang, suggestions["ru"])

        # --- Step 1.5: Pre-process order requests deterministically ---
        order_precheck = await _preprocess_order_request(
            tenant_id, conversation, user_message, state_context, db
        )
        if order_precheck.get("forced_response"):
            # Deterministic response — skip LLM entirely
            # Still persist state_context changes
            conversation.state_context = state_context
            flag_modified(conversation, "state_context")
            await db.flush()
            return order_precheck["forced_response"]

        # Inject order info into state_context if found
        if order_precheck.get("order_context_injection"):
            state_context["_current_order_info"] = order_precheck["order_context_injection"]

        # --- Step 2: Determine current state and build state-aware prompt ---
        current_state = _determine_state(conversation, state_context)

        context_summary = _build_context_summary(state_context)
        system_content = SYSTEM_PROMPT_BASE

        # Inject language directive
        lang_labels = {
            "ru": ("русском", "Пиши ВСЁ по-русски."),
            "uz_cyrillic": ("узбекском (кириллица)", "Пиши ВСЁ по-узбекски кириллицей! НЕ используй русские слова. Жами (не Итого), Саватчада (не В корзине), Мана вариантлар (не Вот варианты), Яна нарса керакми? (не Ещё что-то?). ЗАПРЕЩЕНО использовать русские слова!"),
            "uz_latin": ("узбекском (латиница)", "Write EVERYTHING in Uzbek Latin script! Jami (not Итого), Savatchada (not В корзине), Mana variantlar (not Вот варианты), Yana narsa kerakmi? (not Ещё что-то?). Use ONLY Latin letters! NO Cyrillic!"),
            "en": ("английском", "Write EVERYTHING in English. Product names stay as-is."),
        }
        # Backward compat: old "uz" value
        if detected_lang == "uz":
            detected_lang = "uz_cyrillic"
            state_context["language"] = "uz_cyrillic"
        lang_label, lang_instruction = lang_labels.get(detected_lang, ("русском", "Пиши ВСЁ по-русски."))
        system_content += f"\n\n══════ ТЕКУЩИЙ КОНТЕКСТ ══════"
        system_content += f"\nЯЗЫК КЛИЕНТА: {lang_label}. {lang_instruction}"

        # Inject Telegram profile name so AI can use it as customer name
        tg_name = getattr(conversation, "telegram_first_name", "") or ""
        if tg_name:
            system_content += f"\nИМЯ КЛИЕНТА ИЗ TELEGRAM: {tg_name} (используй как customer_name если клиент не назвал другое)"

        # Add state-specific instructions
        state_prompt = STATE_PROMPTS.get(current_state, "")
        if state_prompt:
            system_content += f"\n\n{state_prompt}"

        if context_summary:
            system_content += f"\n\nSTATE_CONTEXT (данные из предыдущих запросов — используй variant_id отсюда для заказа):\n{context_summary}"

        # Inject pre-checked order info so LLM doesn't have to guess
        current_order_info = state_context.pop("_current_order_info", None)
        if current_order_info:
            system_content += f"\n\nПРОВЕРЕННЫЙ ЗАКАЗ (данные из БД — НЕ выдумывай другой статус!):\n{current_order_info}"

        # FINAL language reminder at end of prompt (LLM pays most attention to end)
        system_content += f"\n\n══════ НАПОМИНАНИЕ ══════\nОТВЕЧАЙ СТРОГО НА {lang_label.upper()} ЯЗЫКЕ! Весь текст, включая списки товаров, цены, вопросы — всё на {lang_label} языке. {lang_instruction}"

        # --- Step 3: Build messages with history (last 20) ---
        history_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(20)
        )
        history_messages = list(reversed(history_result.scalars().all()))

        messages = [{"role": "system", "content": system_content}]

        for msg in history_messages:
            if msg.direction == "inbound":
                messages.append({"role": "user", "content": msg.raw_text or ""})
            elif msg.direction == "outbound" and msg.ai_generated:
                messages.append({"role": "assistant", "content": msg.raw_text or ""})

        messages.append({"role": "user", "content": user_message})

        # --- Step 4: Multi-round tool calling (up to 3 rounds) ---
        final_text = None
        tools_called = set()  # Track which tools were actually called
        cart_before_ai = [item.get("title", "") for item in state_context.get("cart", [])]  # Snapshot cart titles before AI
        for round_num in range(3):
            response = await client.chat.completions.create(
                model=settings.openai_model_main,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=500,
                temperature=0.3,
            )
            assistant_msg = response.choices[0].message

            if not assistant_msg.tool_calls:
                final_text = assistant_msg.content
                break

            # Execute tool calls
            messages.append(assistant_msg.model_dump())
            forced_response = None  # For tools that need deterministic responses
            # Collect tool names in THIS round for guards
            round_tool_names = {tc.function.name for tc in assistant_msg.tool_calls}
            for tool_call in assistant_msg.tool_calls:
                tools_called.add(tool_call.function.name)
                tool_args = json.loads(tool_call.function.arguments)

                # CODE-LEVEL GUARD: block select_for_cart in the same round as get_variant_candidates
                # The AI must show variants to the user first, then wait for their choice.
                if tool_call.function.name == "select_for_cart" and "get_variant_candidates" in round_tool_names:
                    logger.warning("BLOCKED select_for_cart in same round as get_variant_candidates — must show variants first")
                    result = {"error": "Сначала покажи варианты клиенту и дождись его выбора. Нельзя добавлять в корзину автоматически."}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                    continue

                result = await _execute_tool(
                    tool_call.function.name,
                    tool_args,
                    tenant_id=tenant_id,
                    conversation=conversation,
                    state_context=state_context,
                    db=db,
                )

                # Update state_context
                if isinstance(result, dict):
                    state_context = _update_context_from_tool(
                        state_context, tool_call.function.name, tool_args, result
                    )

                # Update conversation state
                new_state = next_state(current_state, tool_call.function.name)
                if new_state != current_state:
                    current_state = new_state
                    conversation.state = new_state

                # Build forced response for order modification tools
                # (LLM keeps asking for address — override its response entirely)
                if isinstance(result, dict) and result.get("success"):
                    forced_response = _build_order_modification_response(
                        tool_call.function.name, result, detected_lang
                    )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

            # If we have a forced response from order modification, use it directly
            if forced_response:
                final_text = forced_response
                break
        else:
            # Max rounds reached, get final response without tools
            response = await client.chat.completions.create(
                model=settings.openai_model_main,
                messages=messages,
                max_tokens=500,
                temperature=0.3,
            )
            final_text = response.choices[0].message.content

        # --- Step 4.5: Post-processing — catch AI hallucinations ---
        if final_text:
            text_lower = final_text.lower()
            cart = state_context.get("cart", [])

            # Catch "added to cart" CLAIMS (past tense) without select_for_cart tool call.
            # IMPORTANT: Only trigger on PAST TENSE ("добавил", "добавлено") — NOT on
            # questions like "Добавить в корзину?" which are legitimate AI responses.
            import re as _re_cart
            # Match past tense claims: "добавил X в корзину", "X добавлено", "added X"
            _cart_claim_patterns = [
                r"добавил\w*\s",       # "добавил", "добавила" (past: I added)
                r"добавлено\b",         # "добавлено" (passive: was added)
                r"\badded\b",           # English "added"
                r"qo'shildi\b",         # Uzbek Latin "was added"
                r"қўшилди\b",           # Uzbek Cyrillic "was added"
            ]
            claims_added = any(_re_cart.search(p, text_lower) for p in _cart_claim_patterns)
            cart_after = [item.get("title", "") for item in cart]
            cart_actually_changed = set(cart_after) != set(cart_before_ai)
            if claims_added and "select_for_cart" not in tools_called and not cart_actually_changed:
                logger.warning("AI claimed to add to cart (past tense) but select_for_cart was never called — overriding")
                if cart:
                    cart_lines = ", ".join(item.get("title", "?") for item in cart)
                    corrections = {
                        "ru": f"В корзине сейчас: {cart_lines}. Какой ещё товар хотите добавить?",
                        "uz_cyrillic": f"Саватчада ҳозир: {cart_lines}. Яна қайси товар қўшамиз?",
                        "uz_latin": f"Savatchada hozir: {cart_lines}. Yana qaysi tovar qo'shamiz?",
                        "en": f"Currently in cart: {cart_lines}. What else would you like to add?",
                    }
                else:
                    corrections = {
                        "ru": "Для добавления в корзину мне нужно сначала проверить наличие. Какой товар вас интересует?",
                        "uz_cyrillic": "Саватчага қўшиш учун аввал мавжудлигини текшириб олишим керак. Қайси товар керак?",
                        "uz_latin": "Savatchaga qo'shish uchun avval mavjudligini tekshirib olishim kerak. Qaysi tovar kerak?",
                        "en": "I need to check availability first before adding to cart. Which product are you interested in?",
                    }
                final_text = corrections.get(detected_lang, corrections["ru"])

            # Catch AI showing prices/stock without calling get_variant_candidates
            import re as _re_check
            has_price_pattern = bool(_re_check.search(r'\d{1,3}[\s,]\d{3}[\s,]\d{3}', final_text))
            price_tools = {"get_variant_candidates", "get_variant_price", "get_variant_stock",
                           "check_order_status", "get_product_candidates", "create_order_draft"}
            if has_price_pattern and not (tools_called & price_tools) and not cart:
                known_prices = set()
                # Prices from variant data
                for prod_info in state_context.get("products", {}).values():
                    for v in prod_info.get("variants", []):
                        try:
                            known_prices.add(int(float(v.get("price", 0))))
                        except (ValueError, TypeError):
                            pass
                    # Prices from product search (price_range like "3290000–4890000")
                    pr = prod_info.get("price_range", "")
                    if pr:
                        for p in _re_check.findall(r'(\d+)', str(pr)):
                            try:
                                known_prices.add(int(p))
                            except ValueError:
                                pass
                found_prices = _re_check.findall(r'(\d{1,3}[\s,]\d{3}[\s,]\d{3})', final_text)
                for fp in found_prices:
                    try:
                        price_int = int(fp.replace(" ", "").replace(",", ""))
                        if price_int > 100000 and price_int not in known_prices and known_prices:
                            logger.warning("AI showed price %s not from tools — potential hallucination", price_int)
                            break
                    except ValueError:
                        pass

            # Catch AI fabricating product specs (battery life, camera, screen, etc.)
            # These should NEVER appear unless get_variant_candidates returned them
            # NOTE: Now that variants have specs in attributes_json, this only triggers
            # when get_variant_candidates was NOT called at all in this conversation turn.
            _FABRICATED_SPEC_PATTERNS = [
                r'\d+\s*(?:соат|час|hour|ч\.?)\s*(?:давомида|ишлайди|работы|работает|battery|батарея)',
                r'(?:батарея|аккумулятор|зарядка|battery)\s*(?:[-—:]?\s*\d+)',
                r'\d+\s*(?:мп|мегапиксел|megapixel|mp)\b',
                r'\d+(?:\.\d+)?[\s"]*(?:дюйм|inch)',
                r'(?:процессор|chipset|чип)\s*[-—:]?\s*\w+\s+\w+',
                r'(?:AMOLED|OLED|IPS|LCD|TFT)\s+(?:дисплей|экран|display)',
                r'\d+\s*(?:Гц|Hz)\s+(?:обновлен|refresh)',
                r'(?:давом этади|ишлайди|етади)\b',  # Uzbek "lasts/works" — spec claims
            ]
            # Only check if get_variant_candidates was NOT called AND no specs exist
            # in state_context (from previous turns)
            has_specs_in_context = any(
                v.get("specs") for prod_info in state_context.get("products", {}).values()
                for v in prod_info.get("variants", [])
                if isinstance(v, dict)
            )
            if "get_variant_candidates" not in tools_called and not has_specs_in_context:
                for pattern in _FABRICATED_SPEC_PATTERNS:
                    if _re_check.search(pattern, final_text, _re_check.IGNORECASE):
                        logger.warning("AI fabricated specs (pattern: %s) — overriding response", pattern)
                        corrections = {
                            "ru": "Я могу показать только цены и наличие. Для подробных характеристик вызови get_variant_candidates. Чем ещё могу помочь?",
                            "uz_cyrillic": "Мен фақат нарх ва мавжудлигини кўрсата оламан. Батафсил характеристикалар учун операторга мурожаат қилинг. Яна нима керак?",
                            "uz_latin": "Men faqat narx va mavjudligini ko'rsata olaman. Batafsil xarakteristikalar uchun operatorga murojaat qiling. Yana nima kerak?",
                            "en": "I can only show prices and availability. For detailed specs, please contact our operator. Anything else I can help with?",
                        }
                        final_text = corrections.get(detected_lang, corrections["ru"])
                        break

            # Catch language mismatch — AI responding in wrong language
            # Especially common: uz_cyrillic conversation but AI replies in Russian
            if detected_lang == "uz_cyrillic" and final_text:
                _russian_markers = ["отлично", "готово", "ваш заказ", "если что", "обращайтесь", "что-нибудь ещё", "спасибо за"]
                _has_russian = sum(1 for m in _russian_markers if m in text_lower)
                _has_uz = any(c in final_text for c in "ўқғҳ")
                if _has_russian >= 2 and not _has_uz:
                    logger.warning("AI responded in Russian instead of uz_cyrillic — fixing")
                    # Try to detect what kind of response it was and replace with appropriate Uzbek
                    if any(w in text_lower for w in ["готово", "обновлён", "обращайтесь"]):
                        final_text = "Тайёр! Буюртмангиз янгиланди 👍 Яна нима керак бўлса, ёзинг!"
                    elif any(w in text_lower for w in ["спасибо", "покупку"]):
                        final_text = "Раҳмат! Харидингиз учун ташаккур 🙏"
            elif detected_lang == "uz_latin" and final_text:
                _cyrillic_count = sum(1 for c in final_text if "\u0400" <= c <= "\u04FF")
                _latin_count = sum(1 for c in final_text if "a" <= c.lower() <= "z")
                if _cyrillic_count > _latin_count and _cyrillic_count > 10:
                    logger.warning("AI responded in Cyrillic instead of uz_latin — fixing")
                    if any(w in text_lower for w in ["готово", "обновлён", "обращайтесь", "тайёр"]):
                        final_text = "Tayyor! Buyurtmangiz yangilandi 👍 Yana nima kerak bo'lsa, yozing!"

        # --- Step 5: Persist state_context + state ---
        # Keep only last 5 products to avoid bloating
        products = state_context.get("products", {})
        if len(products) > 5:
            keys = list(products.keys())
            for k in keys[:-5]:
                del products[k]

        # Log cart state for debugging
        _cart_save = state_context.get("cart", [])
        if _cart_save:
            logger.info("Saving state_context: cart=%s, state=%s", [i.get("title","?") for i in _cart_save], current_state)

        conversation.state_context = state_context
        conversation.state = current_state
        flag_modified(conversation, "state_context")
        await db.flush()

        return final_text

    except Exception:
        logger.exception("AI processing error for tenant %s, conversation %s", tenant_id, conversation_id)
        return None


async def _execute_tool(
    name: str, args: dict, tenant_id: UUID, conversation: Conversation, state_context: dict, db: AsyncSession
) -> dict:
    """Execute a truth tool and return the result."""
    if name == "list_categories":
        return await list_categories(tenant_id, db)

    elif name == "get_product_candidates":
        return await get_product_candidates(tenant_id, args["query"], db)

    elif name == "get_variant_candidates":
        try:
            pid = UUID(args["product_id"])
        except (ValueError, AttributeError):
            return {"error": f"Invalid product_id '{args.get('product_id')}'. Use get_product_candidates first to get valid product UUIDs."}
        return await get_variant_candidates(tenant_id, pid, db)

    elif name == "get_variant_price":
        try:
            vid = UUID(args["variant_id"])
        except (ValueError, AttributeError):
            return {"error": "Invalid variant_id. Use get_variant_candidates first."}
        return await get_variant_price(tenant_id, vid, db)

    elif name == "get_variant_stock":
        try:
            vid = UUID(args["variant_id"])
        except (ValueError, AttributeError):
            return {"error": "Invalid variant_id. Use get_variant_candidates first."}
        return await get_variant_stock(tenant_id, vid, db)

    elif name == "get_delivery_options":
        return await get_delivery_options(tenant_id, args["city"], db)

    elif name == "create_lead":
        try:
            pid = UUID(args["product_id"]) if args.get("product_id") else None
            vid = UUID(args["variant_id"]) if args.get("variant_id") else None
        except (ValueError, AttributeError):
            return {"error": "Invalid UUID. Use get_product_candidates / get_variant_candidates first."}
        return await create_lead(tenant_id, conversation.id, pid, vid, db)

    elif name == "select_for_cart":
        vid_str = args.get("variant_id", "")
        try:
            vid = UUID(vid_str)
        except (ValueError, AttributeError):
            return {"error": f"Invalid variant_id '{vid_str}'. Use variant_id from state_context."}
        qty = int(args.get("qty", 1))

        # GUARD: variant_id must exist in state_context (from get_variant_candidates)
        # This prevents AI from using hallucinated variant IDs
        known_variant_ids = set()
        for prod_info in state_context.get("products", {}).values():
            for v in prod_info.get("variants", []):
                known_variant_ids.add(v.get("variant_id", ""))
        if vid_str not in known_variant_ids:
            return {
                "error": f"variant_id '{vid_str}' не найден. Сначала вызови get_variant_candidates для этого товара, потом используй variant_id из результата.",
                "hint": "Call get_variant_candidates first to get valid variant_ids",
            }

        # Verify variant exists and has stock
        from src.ai.truth_tools import get_variant_stock as _get_stock
        stock_info = await _get_stock(tenant_id, vid, db)
        if stock_info.get("error"):
            return stock_info
        avail = stock_info.get("available_quantity", 0)
        if avail < qty:
            return {"error": f"Недостаточно товара. Доступно: {avail} шт.", "available": avail}

        # Get variant title and price for cart display
        from src.ai.truth_tools import get_variant_price as _get_price
        price_info = await _get_price(tenant_id, vid, db)

        cart = state_context.setdefault("cart", [])
        # Check if already in cart
        for item in cart:
            if item["variant_id"] == vid_str:
                item["qty"] += qty
                return {"status": "updated", "cart": cart, "message": f"Количество обновлено: {item['qty']} шт"}

        cart.append({
            "variant_id": vid_str,
            "title": price_info.get("title", stock_info.get("title", "?")),
            "price": price_info.get("price", 0),
            "qty": qty,
        })
        return {"status": "added", "cart": cart, "message": f"Добавлено в корзину ({len(cart)} товаров)"}

    elif name == "remove_from_cart":
        vid_str = args.get("variant_id", "")
        cart = state_context.get("cart", [])

        if vid_str == "all":
            state_context["cart"] = []
            return {"status": "cleared", "cart": [], "message": "Корзина очищена"}

        # Remove by variant_id or by partial title match
        new_cart = []
        removed = None
        for item in cart:
            if item["variant_id"] == vid_str:
                removed = item
            else:
                new_cart.append(item)

        if not removed:
            # Try matching by title keyword
            keyword = vid_str.lower()
            for item in cart:
                if keyword in item.get("title", "").lower():
                    removed = item
                    new_cart = [i for i in cart if i is not removed]
                    break

        state_context["cart"] = new_cart
        if removed:
            return {"status": "removed", "removed": removed["title"], "cart": new_cart}
        return {"status": "not_found", "cart": new_cart, "message": "Товар не найден в корзине"}

    elif name == "create_order_draft":
        # Validate phone number — MUST be a real number, not placeholder
        phone = (args.get("phone") or "").strip()
        phone_digits = "".join(c for c in phone if c.isdigit())
        if len(phone_digits) < 9 or "XXXX" in phone.upper() or phone_digits == "0" * len(phone_digits):
            return {"error": "Номер телефона обязателен! Спроси у клиента реальный номер телефона. Не придумывай номер."}

        # Validate customer name
        customer_name = (args.get("customer_name") or "").strip()
        if len(customer_name) < 2:
            return {"error": "Имя клиента обязательно! Спроси имя."}

        # Validate city — MUST be provided to calculate delivery
        city = (args.get("city") or "").strip()
        if not city:
            return {"error": "Город не указан! Спроси у клиента город доставки. Доступные города: Ташкент, Самарканд, Бухара, Фергана, Наманган, Андижан, Нукус, Карши, Навои, Джизак, Ургенч, Термез."}

        # Get items from cart
        cart = state_context.get("cart", [])
        logger.info("create_order_draft: cart has %d items: %s", len(cart), [i.get("title","?") for i in cart])
        if not cart:
            return {"error": "Корзина пуста. Сначала добавьте товары через select_for_cart."}

        variant_ids = []
        quantities = []
        for item in cart:
            try:
                variant_ids.append(UUID(item["variant_id"]))
                quantities.append(item.get("qty", 1))
            except (ValueError, AttributeError):
                continue

        if not variant_ids:
            return {"error": "Нет валидных товаров в корзине."}

        # Auto-create lead
        lead_result = await create_lead(tenant_id, conversation.id, None, variant_ids[0], db)
        if lead_result.get("error"):
            return lead_result
        lead_id = UUID(lead_result["lead_id"])

        # Update lead with customer data from order
        from src.leads.models import Lead as LeadModel
        lead_obj = await db.get(LeadModel, lead_id)
        if lead_obj:
            if args.get("customer_name"):
                lead_obj.customer_name = args["customer_name"]
            if args.get("phone"):
                lead_obj.phone = args["phone"]
            if args.get("city"):
                lead_obj.city = args["city"]
            lead_obj.status = "converted"

        result = await create_order_draft(
            tenant_id, lead_id, variant_ids, quantities,
            args.get("customer_name", ""),
            args.get("phone", ""),
            args.get("city"),
            args.get("address"),
            db,
        )

        # Clear cart on success
        if result.get("order_id"):
            state_context["cart"] = []

        return result

    elif name == "get_customer_history":
        from src.ai.truth_tools import get_customer_history
        result = await get_customer_history(tenant_id, conversation.id, db)
        # Save to state_context for later use in create_order_draft
        if result.get("found"):
            state_context["customer"] = {
                "name": result.get("customer_name"),
                "phone": result.get("phone"),
                "city": result.get("city"),
                "address": result.get("address"),
            }
        return result

    elif name == "check_order_status":
        from src.ai.truth_tools import check_order_status
        result = await check_order_status(
            tenant_id, conversation.id,
            args.get("order_number"),
            db,
        )
        # Enrich with policy-based allowed_actions
        if result.get("found"):
            if result.get("status"):
                # Single order
                status = result["status"]
                result["allowed_actions"] = get_allowed_actions(status)
                cancel_policy = can_cancel_order(status)
                edit_policy = can_edit_order(status)
                result["can_cancel"] = cancel_policy
                result["can_edit"] = edit_policy
            elif result.get("orders"):
                # Multiple orders — enrich each
                for order in result["orders"]:
                    status = order.get("status", "")
                    order["allowed_actions"] = get_allowed_actions(status)
        return result

    elif name == "cancel_order":
        from src.ai.truth_tools import cancel_order_by_number
        return await cancel_order_by_number(
            tenant_id, conversation.id,
            args["order_number"],
            db,
        )

    elif name == "add_item_to_order":
        from src.ai.truth_tools import add_item_to_order
        try:
            vid = UUID(args["variant_id"])
        except (ValueError, AttributeError):
            return {"error": "Invalid variant_id. Use get_variant_candidates first."}
        return await add_item_to_order(
            tenant_id, conversation.id,
            args["order_number"],
            vid,
            int(args.get("qty", 1)),
            db,
        )

    elif name == "remove_item_from_order":
        from src.ai.truth_tools import remove_item_from_order
        try:
            vid = UUID(args["variant_id"])
        except (ValueError, AttributeError):
            return {"error": "Invalid variant_id. Use check_order_status to see order items."}
        return await remove_item_from_order(
            tenant_id, conversation.id,
            args["order_number"],
            vid,
            int(args["qty"]) if args.get("qty") else None,
            db,
        )

    elif name == "request_handoff":
        from src.handoffs.models import Handoff
        from src.ai.policies import AI_EDITABLE_STATUSES, LOCKED_STATUSES
        from src.ai.truth_tools import _normalize_order_number

        # --- Guard: check if handoff is actually needed for order-related reasons ---
        reason = args.get("reason", "").lower()
        linked_order_num = args.get("linked_order_number")

        # Try to detect order number from reason if not explicitly provided
        order_to_check = linked_order_num
        if not order_to_check:
            import re as _re
            ord_match = _re.search(r'(?:ORD[- ]?)?([A-Fa-f0-9]{8})', reason)
            if ord_match:
                order_to_check = ord_match.group(0)

        if order_to_check and any(kw in reason for kw in ["изменить", "изменен", "edit", "добавить", "убрать", "удалить", "отменить", "cancel"]):
            from src.orders.models import Order as _Order
            _ord_result = await db.execute(
                select(_Order).where(
                    _Order.tenant_id == tenant_id,
                    _Order.order_number == _normalize_order_number(order_to_check),
                )
            )
            _order = _ord_result.scalar_one_or_none()
            if _order:
                if _order.status in AI_EDITABLE_STATUSES:
                    # AI can handle this! Don't create handoff
                    return {
                        "status": "handoff_rejected",
                        "reason": f"Заказ {_order.order_number} в статусе \"{_order.status}\" — ты можешь изменить его сам! Используй add_item_to_order или remove_item_from_order. НЕ вызывай request_handoff для этого заказа.",
                        "order_number": _order.order_number,
                        "order_status": _order.status,
                        "use_tools": ["add_item_to_order", "remove_item_from_order", "cancel_order"],
                    }
                if _order.status in LOCKED_STATUSES:
                    # No point in handoff — changes are impossible
                    from src.ai.policies import STATUS_LABELS_RU
                    status_label = STATUS_LABELS_RU.get(_order.status, _order.status)
                    return {
                        "status": "handoff_rejected",
                        "reason": f"Заказ {_order.order_number} в статусе \"{status_label}\" — изменения невозможны. Оператор тоже не может помочь. Просто скажи клиенту что изменить нельзя.",
                        "order_number": _order.order_number,
                        "order_status": _order.status,
                    }

        # Find linked order if provided
        linked_order_id = None
        if linked_order_num:
            from src.orders.models import Order
            order_result = await db.execute(
                select(Order).where(
                    Order.tenant_id == tenant_id,
                    Order.order_number == _normalize_order_number(linked_order_num),
                )
            )
            order = order_result.scalar_one_or_none()
            if order:
                linked_order_id = order.id

        # Build summary from recent context
        summary_parts = []
        cart = state_context.get("cart", [])
        if cart:
            summary_parts.append(f"Корзина: {len(cart)} товаров")
        orders = state_context.get("orders", [])
        if orders:
            summary_parts.append(f"Заказы: {', '.join(o.get('order_number', '?') for o in orders)}")
        summary = "; ".join(summary_parts) if summary_parts else None

        handoff = Handoff(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            reason=args.get("reason", "AI requested handoff"),
            priority=args.get("priority", "normal"),
            summary=summary,
            linked_order_id=linked_order_id,
        )
        db.add(handoff)
        conversation.status = "handoff"
        conversation.ai_enabled = False
        await db.flush()
        return {"status": "handoff_created", "reason": args.get("reason")}

    else:
        return {"error": f"Unknown tool: {name}"}
