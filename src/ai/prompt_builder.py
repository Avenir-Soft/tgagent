"""System prompt builder for AI orchestrator.

Constructs the full system prompt from base template + language + tone +
state-specific instructions + context summary.

Adapted for Easy Tour — tour booking context.
"""

from src.ai.prompts import SYSTEM_PROMPT_BASE, STATE_PROMPTS
from src.ai.responses import _build_context_summary
from src.conversations.models import Conversation


_LANG_LABELS = {
    "ru": (
        "русском",
        "Пиши ВСЁ по-русски. ВСЕ ответы на русском — категории, туры, статусы, ошибки, 'тур не найден'. "
        "НИКАКИХ узбекских слов! 'Afsuski' → 'К сожалению', 'mavjud emas' → 'нет в наличии', "
        "'Buyurtma' → 'Заказ', 'so\\'m' → 'сум'. АБСОЛЮТНО ВСЁ по-русски!",
    ),
    "uz_cyrillic": (
        "ўзбекча (кириллица)",
        "Ёз ҲАММАсини ўзбекча кириллицада! Рус сўзларини ишлатма. "
        "Жами (Итого эмас), Мана вариантлар (Вот варианты эмас), "
        "Яна нарса керакми? (Ещё что-то? эмас). Рус сўзлар ТАЪҚИҚЛАНГАН!",
    ),
    "uz_latin": (
        "o'zbekcha (lotin)",
        "Yoz HAMMAsini o'zbekcha lotin yozuvida! Rus so'zlarini ishlatma. "
        "Jami (Итого emas), Mana variantlar (Вот варианты emas), "
        "Yana narsa kerakmi? (Ещё что-то? emas). FAQAT lotin harflar! Kirill TAQIQLANGAN!",
    ),
    "en": ("English", "Write EVERYTHING in English. Tour names stay as-is."),
}

_TONE_INSTRUCTIONS = {
    "friendly_sales": "Do'stona va samimiy gapir, emoji ishlataver, jonli tur konsultanti kabi.",
    "formal": "Rasmiy va hurmatli gapir. Emoji yo'q, sleng yo'q.",
    "casual": "Juda norasmiy gapir, do'st kabi. Hazil qilsa bo'ladi, emoji ishlataver.",
}


def build_system_prompt(
    conversation: Conversation,
    state_context: dict,
    detected_lang: str,
    ai_settings,
    current_state: str,
) -> str:
    """Build complete system prompt with all context injections."""
    system_content = SYSTEM_PROMPT_BASE

    # --- Language directive ---
    lang_label, lang_instruction = _LANG_LABELS.get(detected_lang, _LANG_LABELS["uz_latin"])
    system_content += "\n\n══════ JORIY KONTEKST ══════"
    system_content += f"\nMIJOZ TILI: {lang_label}. {lang_instruction}"

    # --- Tone ---
    if ai_settings:
        tone_hint = _TONE_INSTRUCTIONS.get(ai_settings.tone, _TONE_INSTRUCTIONS["friendly_sales"])
        system_content += f"\nMUOMILA USLUBI: {tone_hint}"

        if ai_settings.confirm_before_order:
            system_content += (
                "\nBUYURTMANI TASDIQLASH: create_order_draft chaqirishdan OLDIN ALBATTA mijozdan tasdiq ol: "
                "turni, sanani, ishtirokchilar sonini, ism va telefon raqamini qayta aytib 'Hammasi to'g'rimi?' deb so'ra. "
                "Faqat aniq 'ha' javobidan keyin buyurtma yarat."
            )

    # --- Telegram profile name ---
    tg_name = getattr(conversation, "telegram_first_name", "") or ""
    if tg_name:
        system_content += f"\nMIJOZ ISMI (TELEGRAM): {tg_name} (agar mijoz boshqa ism aytmasa, shu ismni customer_name sifatida ishlatilsin)"

    # --- State-specific instructions ---
    state_prompt = STATE_PROMPTS.get(current_state, "")
    if state_prompt:
        system_content += f"\n\n{state_prompt}"

    # --- Context summary from state_context ---
    context_summary = _build_context_summary(state_context)
    if context_summary:
        system_content += f"\n\nSTATE_CONTEXT (oldingi so'rovlar ma'lumotlari — buyurtma uchun variant_id shu yerdan ol):\n{context_summary}"

    # --- Pre-checked booking info ---
    current_order_info = state_context.pop("_current_order_info", None)
    if current_order_info:
        system_content += f"\n\nTEKSHIRILGAN BUYURTMA (BD dan ma'lumot — boshqa holat TO'QIMA!):\n{current_order_info}"

    # --- Customer photo description ---
    photo_desc = state_context.pop("_customer_photo_description", None)
    if photo_desc:
        system_content += f"\n\nMIJOZ FOTO TAVSIFI: {photo_desc}"

    # --- Final language reminder (LLM pays most attention to end) ---
    if detected_lang == "ru":
        system_content += (
            "\n\n══════ ВАЖНО: ЯЗЫК ОТВЕТА ══════\n"
            "ОТВЕЧАЙ ТОЛЬКО ПО-РУССКИ! Весь текст — по-русски. Названия туров, категории, "
            "статусы, сообщения об ошибках, 'тур не найден' — ВСЁ по-русски. "
            "ЗАПРЕЩЕНО: узбекские слова, латиница, кириллица-узбекский. ТОЛЬКО русский язык!"
        )
    elif detected_lang == "en":
        system_content += (
            "\n\n══════ IMPORTANT: RESPONSE LANGUAGE ══════\n"
            "RESPOND ONLY IN ENGLISH! All text — in English. Tour names, categories, "
            "statuses, error messages — EVERYTHING in English."
        )
    else:
        system_content += (
            f"\n\n══════ ESLATMA ══════\n"
            f"JAVOB BER FAQAT {lang_label.upper()} TILIDA! Barcha matn, jumladan turlar ro'yxati, "
            f"narxlar, savollar — hammasi {lang_label} tilida. {lang_instruction}"
        )

    return system_content
