"""Order request pre-processor — deterministic handling BEFORE LLM.

Detects order numbers in user messages and handles them without LLM:
- Not found → forced "not found" response
- Wrong owner → forced "not found" (no info leak)
- Locked status + modify → forced refusal
- Processing + modify → create handoff
- Editable + modify → inject order info for LLM
- Status check → inject order info for LLM
"""

import logging
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.conversations.models import Conversation

logger = logging.getLogger(__name__)

# Keywords that indicate order modification intent
ORDER_MODIFY_KEYWORDS = [
    "изменить", "изменит", "измени", "изменю", "поменять", "поменяй",
    "добавить", "добавит", "добавь", "добавишь", "добавляй",
    "убрать", "убери", "удалить", "удали",
    "отменить", "отмени", "отменяй",
    "редактировать", "edit", "cancel",
]
ORDER_STATUS_KEYWORDS = ["статус", "проверить", "проверь", "где мой", "когда доставка", "заказ"]

# Two patterns: with ORD prefix (always valid) and bare hex (must contain a letter a-f)
_ORDER_NUMBER_PATTERN_FULL = re.compile(r'\bORD[- ]?([A-Fa-f0-9]{8})\b', re.IGNORECASE)
_ORDER_NUMBER_PATTERN_BARE = re.compile(r'\b([0-9]*[A-Fa-f][A-Fa-f0-9]*)\b')

# States where we should NOT try to detect order numbers (user is providing address/phone)
_SKIP_STATES = {"cart", "checkout"}


async def preprocess_order_request(
    tenant_id: UUID,
    conversation: Conversation,
    user_message: str,
    state_context: dict,
    db: AsyncSession,
    ai_settings=None,
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

    # Skip order detection in cart/checkout state
    current_conv_state = conversation.state or "idle"
    if current_conv_state in _SKIP_STATES:
        return {}

    # Extract order numbers — first try with ORD prefix (always reliable)
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
    is_modify = any(kw in text_lower for kw in ORDER_MODIFY_KEYWORDS)
    status = order.status
    status_label = STATUS_LABELS_RU.get(status, status)

    # Build items list (batch load variant titles to avoid N+1)
    items_text, total_fmt = await _format_order_items(order, db)

    # --- Handle modification requests deterministically ---
    if is_modify:
        return await _handle_modification(
            tenant_id, conversation, order, status, status_label,
            items_text, total_fmt, db, ai_settings,
        )

    # --- Handle status check ---
    return _build_order_injection(order, status, status_label, items_text, total_fmt, ai_settings)


async def _format_order_items(order, db) -> tuple[str, str]:
    """Format order items into text lines. Returns (items_text, total_fmt)."""
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
        items_lines.append(f"- {title} x{item.qty} — {price_fmt} сум")

    items_text = "\n".join(items_lines) if items_lines else "Нет товаров"
    try:
        total_fmt = f"{int(order.total_amount):,}".replace(",", " ")
    except (ValueError, TypeError):
        total_fmt = str(order.total_amount)

    return items_text, total_fmt


async def _handle_modification(
    tenant_id, conversation, order, status, status_label,
    items_text, total_fmt, db, ai_settings,
):
    """Handle order modification requests deterministically."""
    from src.ai.policies import AI_EDITABLE_STATUSES, LOCKED_STATUSES

    if status in LOCKED_STATUSES:
        return {
            "forced_response": f'Заказ {order.order_number} в статусе "{status_label}" — изменения невозможны. Могу помочь с чем-то другим!'
        }

    if status == "processing":
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
            "forced_response": f"Заказ {order.order_number} сейчас в обработке. Для изменений подключу оператора, подождите немного \U0001f64f"
        }

    if status in AI_EDITABLE_STATUSES:
        if ai_settings and ai_settings.require_operator_for_edit:
            from src.handoffs.models import Handoff
            handoff = Handoff(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                reason=f"Клиент хочет изменить заказ {order.order_number} (оператор обязателен по настройкам)",
                priority="high",
                summary=f"Заказ {order.order_number} на сумму {total_fmt} сум, клиент хочет изменить (require_operator_for_edit=True)",
                linked_order_id=order.id,
            )
            db.add(handoff)
            conversation.status = "handoff"
            conversation.ai_enabled = False
            await db.flush()
            return {
                "forced_response": f"Для изменения заказа {order.order_number} подключу оператора, подождите немного \U0001f64f"
            }
        # AI can help
        order_info = (
            f"Заказ {order.order_number} — статус: {status_label}\n"
            f"Товары в заказе:\n{items_text}\n"
            f"Итого: {total_fmt} сум\n"
            f"СТАТУС ПОЗВОЛЯЕТ ИЗМЕНЕНИЕ! Используй add_item_to_order / remove_item_from_order для этого заказа.\n"
            f"НЕ вызывай request_handoff — ты МОЖЕШЬ изменить этот заказ сам!"
        )
        return {"order_context_injection": order_info}

    return {}


def _build_order_injection(order, status, status_label, items_text, total_fmt, ai_settings):
    """Build order context injection for LLM (status check)."""
    from src.ai.policies import AI_EDITABLE_STATUSES, LOCKED_STATUSES

    order_info = (
        f"Заказ {order.order_number} — статус: {status_label}\n"
        f"Товары:\n{items_text}\n"
        f"Итого: {total_fmt} сум"
    )
    if status in AI_EDITABLE_STATUSES:
        if ai_settings and ai_settings.require_operator_for_edit:
            order_info += "\nДля изменений нужен оператор (настройки магазина). Используй request_handoff."
        else:
            order_info += "\nСтатус позволяет изменение (add_item_to_order / remove_item_from_order)."
    elif status in LOCKED_STATUSES:
        order_info += f'\nСтатус "{status_label}" — изменения НЕВОЗМОЖНЫ.'
    return {"order_context_injection": order_info}
