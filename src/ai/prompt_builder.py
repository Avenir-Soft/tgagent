"""System prompt builder for AI orchestrator.

Constructs the full system prompt from base template + language + tone +
state-specific instructions + context summary.
"""

from src.ai.prompts import SYSTEM_PROMPT_BASE, STATE_PROMPTS
from src.ai.responses import _build_context_summary
from src.conversations.models import Conversation


_LANG_LABELS = {
    "ru": ("русском", "Пиши ВСЁ по-русски."),
    "uz_cyrillic": (
        "узбекском (кириллица)",
        "Пиши ВСЁ по-узбекски кириллицей! НЕ используй русские слова. "
        "Жами (не Итого), Саватчада (не В корзине), Мана вариантлар (не Вот варианты), "
        "Яна нарса керакми? (не Ещё что-то?). ЗАПРЕЩЕНО использовать русские слова!",
    ),
    "uz_latin": (
        "узбекском (латиница)",
        "Write EVERYTHING in Uzbek Latin script! Jami (not Итого), Savatchada (not В корзине), "
        "Mana variantlar (not Вот варианты), Yana narsa kerakmi? (not Ещё что-то?). "
        "Use ONLY Latin letters! NO Cyrillic!",
    ),
    "en": ("английском", "Write EVERYTHING in English. Product names stay as-is."),
}

_TONE_INSTRUCTIONS = {
    "friendly_sales": "Общайся дружелюбно, с эмодзи, как живой продавец-консультант.",
    "formal": "Общайся формально и вежливо. Без эмодзи, без сленга. Пиши 'Вы' с заглавной.",
    "casual": "Общайся максимально неформально, как друг. Можно шутить, использовать эмодзи.",
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
    lang_label, lang_instruction = _LANG_LABELS.get(detected_lang, _LANG_LABELS["ru"])
    system_content += "\n\n══════ ТЕКУЩИЙ КОНТЕКСТ ══════"
    system_content += f"\nЯЗЫК КЛИЕНТА: {lang_label}. {lang_instruction}"

    # --- Tone ---
    if ai_settings:
        tone_hint = _TONE_INSTRUCTIONS.get(ai_settings.tone, _TONE_INSTRUCTIONS["friendly_sales"])
        system_content += f"\nТОН ОБЩЕНИЯ: {tone_hint}"

        if ai_settings.confirm_before_order:
            system_content += (
                "\nПОДТВЕРЖДЕНИЕ ЗАКАЗА: Перед вызовом create_order_draft ОБЯЗАТЕЛЬНО подтверди "
                "у клиента: перечисли товары, итоговую сумму, адрес и спроси 'Всё верно, оформляем?'. "
                "Только после явного 'да' создавай заказ."
            )

    # --- Telegram profile name ---
    tg_name = getattr(conversation, "telegram_first_name", "") or ""
    if tg_name:
        system_content += f"\nИМЯ КЛИЕНТА ИЗ TELEGRAM: {tg_name} (используй как customer_name если клиент не назвал другое)"

    # --- State-specific instructions ---
    state_prompt = STATE_PROMPTS.get(current_state, "")
    if state_prompt:
        system_content += f"\n\n{state_prompt}"

    # --- Context summary from state_context ---
    context_summary = _build_context_summary(state_context)
    if context_summary:
        system_content += f"\n\nSTATE_CONTEXT (данные из предыдущих запросов — используй variant_id отсюда для заказа):\n{context_summary}"

    # --- Pre-checked order info ---
    current_order_info = state_context.pop("_current_order_info", None)
    if current_order_info:
        system_content += f"\n\nПРОВЕРЕННЫЙ ЗАКАЗ (данные из БД — НЕ выдумывай другой статус!):\n{current_order_info}"

    # --- Final language reminder (LLM pays most attention to end) ---
    system_content += (
        f"\n\n══════ НАПОМИНАНИЕ ══════\n"
        f"ОТВЕЧАЙ СТРОГО НА {lang_label.upper()} ЯЗЫКЕ! Весь текст, включая списки товаров, "
        f"цены, вопросы — всё на {lang_label} языке. {lang_instruction}"
    )

    return system_content
