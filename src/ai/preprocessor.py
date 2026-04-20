"""Booking request pre-processor — deterministic handling BEFORE LLM.

Detects booking numbers in user messages and handles them without LLM:
- Not found → forced "not found" response
- Wrong owner → forced "not found" (no info leak)
- Locked status + modify → forced refusal
- Editable + modify → inject order info for LLM
- Status check → inject order info for LLM

Adapted for Easy Tour — tour booking context.
"""

import logging
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.conversations.models import Conversation

logger = logging.getLogger(__name__)

# Keywords that indicate booking modification intent (Uzbek + Russian + English)
ORDER_MODIFY_KEYWORDS = [
    # Uzbek Latin
    "o'zgartir", "o'zgartirib", "o'zgartirmoq", "ozgartir",
    "bekor", "bekor qil", "bekor qilish",
    "tahrirlash", "tuzatish",
    # Russian
    "изменить", "изменит", "измени", "поменять", "поменяй",
    "отменить", "отмени", "отменяй",
    "редактировать",
    # English
    "edit", "cancel", "change", "modify",
]
ORDER_STATUS_KEYWORDS = [
    # Uzbek Latin
    "holat", "tekshir", "tekshirish", "buyurtma", "bron", "bronlash",
    "qachon", "qaerda",
    # Russian
    "статус", "проверить", "проверь", "заказ", "бронь",
    # English
    "status", "check", "order", "booking",
]

# Two patterns: with BK prefix (always valid) and bare hex (must contain a letter a-f)
_ORDER_NUMBER_PATTERN_FULL = re.compile(r'\bBK[- ]?([A-Fa-f0-9]{8})\b', re.IGNORECASE)
_ORDER_NUMBER_PATTERN_BARE = re.compile(r'\b([0-9]*[A-Fa-f][A-Fa-f0-9]*)\b')

# States where we should NOT try to detect booking numbers (user is providing name/phone)
_SKIP_STATES = {"booking"}

# ── Multi-language forced response templates ──────────────────────────────────

_ORDER_NOT_FOUND = {
    "uz_latin": "Buyurtma {num} topilmadi. Raqamni tekshirib qaytadan yuboring.",
    "uz_cyrillic": "Буюртма {num} топилмади. Рақамни текшириб қайтадан юборинг.",
    "ru": "Заказ {num} не найден. Проверьте номер и отправьте снова.",
    "en": "Order {num} not found. Please check the number and try again.",
}

_ORDER_LOCKED = {
    "uz_latin": 'Buyurtma {num} "{status}" holatida — o\'zgartirish mumkin emas. Boshqa narsa bilan yordam bera olamanmi?',
    "uz_cyrillic": 'Буюртма {num} "{status}" ҳолатида — ўзгартириш мумкин эмас. Бошқа нарса билан ёрдам бера оламанми?',
    "ru": 'Заказ {num} в статусе "{status}" — изменение невозможно. Могу помочь чем-то ещё?',
    "en": 'Order {num} is "{status}" — changes are not possible. Can I help with anything else?',
}

_ORDER_HANDOFF = {
    "uz_latin": "Buyurtma {num} ni o'zgartirish uchun operatorni chaqiraman, biroz kuting \U0001f64f",
    "uz_cyrillic": "Буюртма {num} ни ўзгартириш учун операторни чақираман, бироз кутинг \U0001f64f",
    "ru": "Для изменения заказа {num} подключаю оператора, подождите немного \U0001f64f",
    "en": "Connecting operator to modify order {num}, please wait \U0001f64f",
}


async def preprocess_order_request(
    tenant_id: UUID,
    conversation: Conversation,
    user_message: str,
    state_context: dict,
    db: AsyncSession,
    ai_settings=None,
    detected_lang: str = "uz_latin",
) -> dict:
    """Pre-process user message to detect booking numbers and handle deterministically.

    Returns:
        - {"forced_response": "..."} to skip LLM entirely
        - {"order_context_injection": "..."} to enrich LLM context
        - {} if no booking detected
    """
    from src.orders.models import Order
    from src.leads.models import Lead
    from src.ai.policies import AI_EDITABLE_STATUSES, LOCKED_STATUSES, get_status_label
    from src.ai.truth_tools import _normalize_order_number

    text_lower = user_message.lower()

    # Skip booking detection in booking state (collecting name/phone)
    current_conv_state = conversation.state or "idle"
    if current_conv_state in _SKIP_STATES:
        return {}

    # Extract booking numbers — first try with BK prefix (always reliable)
    full_matches = _ORDER_NUMBER_PATTERN_FULL.findall(user_message)
    if full_matches:
        raw_order_num = full_matches[0]
    else:
        # Bare hex — must contain at least one letter [a-f] AND have order-related keywords
        has_order_intent = any(kw in text_lower for kw in ORDER_MODIFY_KEYWORDS + ORDER_STATUS_KEYWORDS)
        if not has_order_intent:
            return {}
        bare_matches = _ORDER_NUMBER_PATTERN_BARE.findall(user_message)
        valid_bare = [m for m in bare_matches if len(m) == 8 and any(c in 'abcdefABCDEF' for c in m)]
        if not valid_bare:
            return {}
        raw_order_num = valid_bare[0]

    order_number = _normalize_order_number(raw_order_num)

    # Look up booking
    order_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.order_number == order_number,
        ).options(selectinload(Order.items))
    )
    order = order_result.scalar_one_or_none()

    if not order:
        tmpl = _ORDER_NOT_FOUND.get(detected_lang, _ORDER_NOT_FOUND["uz_latin"])
        return {"forced_response": tmpl.format(num=raw_order_num)}

    # Check ownership
    if order.lead_id:
        lead_result = await db.execute(select(Lead).where(Lead.id == order.lead_id))
        lead = lead_result.scalar_one_or_none()
        if lead and lead.telegram_user_id != conversation.telegram_user_id:
            tmpl = _ORDER_NOT_FOUND.get(detected_lang, _ORDER_NOT_FOUND["uz_latin"])
            return {"forced_response": tmpl.format(num=raw_order_num)}

    # Determine intent
    is_modify = any(kw in text_lower for kw in ORDER_MODIFY_KEYWORDS)
    status = order.status
    status_label = get_status_label(status, detected_lang)

    # Build items list
    items_text, total_fmt = await _format_order_items(order, db)

    # --- Handle modification requests deterministically ---
    if is_modify:
        return await _handle_modification(
            tenant_id, conversation, order, status, status_label,
            items_text, total_fmt, db, ai_settings, detected_lang,
        )

    # --- Handle status check ---
    return _build_order_injection(order, status, status_label, items_text, total_fmt, ai_settings)


async def _format_order_items(order, db) -> tuple[str, str]:
    """Format booking items into text lines. Returns (items_text, total_fmt)."""
    from src.catalog.models import ProductVariant

    variant_ids = [item.product_variant_id for item in order.items if item.product_variant_id]
    variant_titles: dict = {}
    if variant_ids:
        vr = await db.execute(
            select(ProductVariant.id, ProductVariant.title).where(ProductVariant.id.in_(variant_ids))
        )
        variant_titles = {vid: vtitle for vid, vtitle in vr.all()}

    items_lines = []
    for item in order.items:
        title = variant_titles.get(item.product_variant_id, "?") if item.product_variant_id else "?"
        try:
            price_fmt = f"{int(item.total_price):,}".replace(",", " ")
        except (ValueError, TypeError):
            price_fmt = str(item.total_price)
        items_lines.append(f"- {title} x{item.qty} kishi — {price_fmt} so'm")

    items_text = "\n".join(items_lines) if items_lines else "Turlar yo'q"
    try:
        total_fmt = f"{int(order.total_amount):,}".replace(",", " ")
    except (ValueError, TypeError):
        total_fmt = str(order.total_amount)

    return items_text, total_fmt


async def _handle_modification(
    tenant_id, conversation, order, status, status_label,
    items_text, total_fmt, db, ai_settings, detected_lang="uz_latin",
):
    """Handle booking modification requests deterministically."""
    from src.ai.policies import AI_EDITABLE_STATUSES, LOCKED_STATUSES

    if status in LOCKED_STATUSES:
        tmpl = _ORDER_LOCKED.get(detected_lang, _ORDER_LOCKED["uz_latin"])
        return {
            "forced_response": tmpl.format(num=order.order_number, status=status_label)
        }

    if status in AI_EDITABLE_STATUSES:
        if ai_settings and ai_settings.require_operator_for_edit:
            from src.handoffs.models import Handoff
            handoff = Handoff(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                reason=f"Customer wants to modify order {order.order_number} (operator required)",
                priority="high",
                summary=f"Order {order.order_number}, {total_fmt} UZS, customer wants changes (require_operator_for_edit=True)",
                linked_order_id=order.id,
            )
            db.add(handoff)
            conversation.status = "handoff"
            conversation.ai_enabled = False
            await db.flush()
            tmpl = _ORDER_HANDOFF.get(detected_lang, _ORDER_HANDOFF["uz_latin"])
            return {
                "forced_response": tmpl.format(num=order.order_number)
            }
        # AI can help — inject info for LLM
        order_info = (
            f"Buyurtma {order.order_number} — holat: {status_label}\n"
            f"Turlar:\n{items_text}\n"
            f"Jami: {total_fmt} so'm\n"
            f"HOLAT O'ZGARTIRISH MUMKIN! cancel_order yoki request_handoff chaqir.\n"
            f"Buyurtmadagi turni almashtirish mumkin emas — faqat bekor qilish va qayta buyurtma berish."
        )
        return {"order_context_injection": order_info}

    return {}


def _build_order_injection(order, status, status_label, items_text, total_fmt, ai_settings):
    """Build booking context injection for LLM (status check)."""
    from src.ai.policies import AI_EDITABLE_STATUSES, LOCKED_STATUSES

    order_info = (
        f"Buyurtma {order.order_number} — holat: {status_label}\n"
        f"Turlar:\n{items_text}\n"
        f"Jami: {total_fmt} so'm"
    )
    if status in AI_EDITABLE_STATUSES:
        if ai_settings and ai_settings.require_operator_for_edit:
            order_info += "\nO'zgartirish uchun operator kerak. request_handoff chaqir."
        else:
            order_info += "\nHolat o'zgartirish mumkin. cancel_order chaqirish mumkin."
    elif status in LOCKED_STATUSES:
        order_info += f'\nHolat "{status_label}" — o\'zgartirish MUMKIN EMAS.'
    return {"order_context_injection": order_info}
