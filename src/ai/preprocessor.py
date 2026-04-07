"""Order request pre-processor for AI orchestrator.

Deterministic handling of order-related messages BEFORE invoking the LLM.
Detects order numbers, checks ownership, and returns forced responses
or context injections depending on the order status and user intent.
"""

import re

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.conversations.models import Conversation


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
_ORDER_NUMBER_PATTERN_FULL = re.compile(r'\bORD[- ]?([A-Fa-f0-9]{8})\b', re.IGNORECASE)
_ORDER_NUMBER_PATTERN_BARE = re.compile(r'\b([0-9]*[A-Fa-f][A-Fa-f0-9]*)\b')
# Phone number pattern — exclude from bare hex matching
_PHONE_PATTERN = re.compile(r'[\+]?\d[\d\s\-()]{7,}')
# States where we should NOT try to detect order numbers (user is providing address/phone)
_ORDER_PREPROCESS_SKIP_STATES = {"cart", "checkout"}


_I18N_ORDER_NOT_FOUND = {
    "ru": "Заказ с номером {num} не найден. Проверьте номер и попробуйте снова.",
    "en": "Order {num} not found. Please check the number and try again.",
    "uz_latin": "Buyurtma {num} topilmadi. Raqamni tekshirib, qaytadan urinib ko'ring.",
    "uz_cyrillic": "Буюртма {num} топилмади. Рақамни текшириб, қайтадан уриниб кўринг.",
}
_I18N_ORDER_LOCKED = {
    "ru": "Заказ {num} в статусе \"{status}\" — изменения невозможны. Могу помочь с чем-то другим!",
    "en": "Order {num} is \"{status}\" — changes are not possible. Can I help with something else?",
    "uz_latin": "Buyurtma {num} \"{status}\" holatida — o'zgartirib bo'lmaydi. Boshqa narsa yordam beraymi?",
    "uz_cyrillic": "Буюртма {num} \"{status}\" ҳолатида — ўзгартириб бўлмайди. Бошқа нарса ёрдам берайми?",
}
_I18N_ORDER_PROCESSING = {
    "ru": "Заказ {num} сейчас в обработке. Для изменений подключу оператора, подождите немного 🙏",
    "en": "Order {num} is being processed. I'll connect an operator for changes, please wait 🙏",
    "uz_latin": "Buyurtma {num} hozir ishlov berilmoqda. O'zgartirish uchun operatorni ulayman, biroz kuting 🙏",
    "uz_cyrillic": "Буюртма {num} ҳозир ишлов берилмоқда. Ўзгартириш учун операторни улайман, бироз кутинг 🙏",
}


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

    text_lower = user_message.lower()

    current_conv_state = conversation.state or "idle"

    # Extract order numbers — first try with ORD prefix (always reliable, even in cart/checkout)
    full_matches = _ORDER_NUMBER_PATTERN_FULL.findall(user_message)
    if full_matches:
        raw_order_num = full_matches[0]
    else:
        # Skip bare hex detection in cart/checkout — user is providing address/phone
        if current_conv_state in _ORDER_PREPROCESS_SKIP_STATES:
            return {}
        # Bare hex — must contain at least one letter [a-f] to avoid matching phone numbers
        # AND message must have order-related keywords
        has_order_intent = any(kw in text_lower for kw in _ORDER_MODIFY_KEYWORDS + _ORDER_STATUS_KEYWORDS)
        if not has_order_intent:
            return {}
        # Strip phone numbers before searching for bare hex order numbers
        text_no_phones = _PHONE_PATTERN.sub("", user_message)
        bare_matches = _ORDER_NUMBER_PATTERN_BARE.findall(text_no_phones)
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

    lang = state_context.get("language", "ru")

    if not order:
        return {"forced_response": _I18N_ORDER_NOT_FOUND.get(lang, _I18N_ORDER_NOT_FOUND["ru"]).format(num=raw_order_num)}

    # Check ownership
    if order.lead_id:
        lead_result = await db.execute(select(Lead).where(Lead.id == order.lead_id))
        lead = lead_result.scalar_one_or_none()
        if lead and lead.telegram_user_id != conversation.telegram_user_id:
            return {"forced_response": _I18N_ORDER_NOT_FOUND.get(lang, _I18N_ORDER_NOT_FOUND["ru"]).format(num=raw_order_num)}

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
                "forced_response": _I18N_ORDER_LOCKED.get(lang, _I18N_ORDER_LOCKED["ru"]).format(num=order.order_number, status=status_label)
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
            await db.flush()
            return {
                "forced_response": _I18N_ORDER_PROCESSING.get(lang, _I18N_ORDER_PROCESSING["ru"]).format(num=order.order_number)
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
