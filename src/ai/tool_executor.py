"""Tool executor — dispatches AI tool calls to truth_tools and handles guards.

Each tool gets validated inputs, guard checks, and enriched results.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.policies import (
    can_cancel_order,
    can_edit_order,
    get_allowed_actions,
    AI_EDITABLE_STATUSES,
    LOCKED_STATUSES,
)
from src.ai.truth_tools import (
    list_categories,
    get_product_candidates,
    get_variant_candidates,
    get_delivery_options,
    create_lead,
    create_order_draft,
)
from src.conversations.models import Conversation

logger = logging.getLogger(__name__)


async def execute_tool(
    name: str,
    args: dict,
    tenant_id: UUID,
    conversation: Conversation,
    state_context: dict,
    db: AsyncSession,
    ai_settings=None,
) -> dict:
    """Execute a truth tool and return the result."""

    if name == "list_categories":
        return await list_categories(tenant_id, db)

    elif name == "get_product_candidates":
        return await _handle_product_candidates(tenant_id, args, db, ai_settings)

    elif name == "get_variant_candidates":
        return await _handle_variant_candidates(tenant_id, args, db, ai_settings)

    elif name == "get_delivery_options":
        return await get_delivery_options(tenant_id, args["city"], db)

    elif name == "create_lead":
        return await _handle_create_lead(tenant_id, args, conversation, db)

    elif name == "select_for_cart":
        return await _handle_select_for_cart(tenant_id, args, state_context, db)

    elif name == "remove_from_cart":
        return _handle_remove_from_cart(args, state_context)

    elif name == "create_order_draft":
        return await _handle_create_order_draft(tenant_id, args, conversation, state_context, db)

    elif name == "get_customer_history":
        return await _handle_customer_history(tenant_id, conversation, state_context, db)

    elif name == "check_order_status":
        return await _handle_check_order_status(tenant_id, args, conversation, db, ai_settings)

    elif name == "cancel_order":
        from src.ai.truth_tools import cancel_order_by_number
        return await cancel_order_by_number(
            tenant_id, conversation.id, args["order_number"], db, ai_settings=ai_settings,
        )

    elif name == "add_item_to_order":
        return await _handle_add_item_to_order(tenant_id, args, conversation, db)

    elif name == "remove_item_from_order":
        return await _handle_remove_item_from_order(tenant_id, args, conversation, db)

    elif name == "request_return":
        from src.ai.truth_tools import request_return
        return await request_return(
            tenant_id, conversation.id, args["order_number"],
            args.get("reason", "Не указана"), db, ai_settings=ai_settings,
        )

    elif name == "request_handoff":
        return await _handle_request_handoff(tenant_id, args, conversation, state_context, db, ai_settings)

    else:
        return {"error": f"Unknown tool: {name}"}


# ──────────────────────────────────────────────
# Individual tool handlers
# ──────────────────────────────────────────────


async def _handle_product_candidates(tenant_id, args, db, ai_settings):
    result = await get_product_candidates(tenant_id, args["query"], db)
    if ai_settings and ai_settings.require_handoff_for_unknown_product:
        if not result.get("found"):
            result["_handoff_hint"] = "Товар не найден в каталоге. Подключи оператора через request_handoff — он поможет клиенту."
    return result


async def _handle_variant_candidates(tenant_id, args, db, ai_settings):
    try:
        pid = UUID(args["product_id"])
    except (ValueError, AttributeError):
        return {"error": f"Invalid product_id '{args.get('product_id')}'. Use get_product_candidates first to get valid product UUIDs."}
    result = await get_variant_candidates(tenant_id, pid, db)
    if ai_settings and result.get("found") and result.get("variants"):
        max_v = ai_settings.max_variants_in_reply or 5
        variants = result["variants"]
        if len(variants) > max_v:
            result["variants"] = variants[:max_v]
            result["total_variants"] = len(variants)
            result["showing"] = max_v
            result["note"] = f"Показано {max_v} из {len(variants)} вариантов. Спроси клиента если нужны другие."
    return result


async def _handle_create_lead(tenant_id, args, conversation, db):
    try:
        pid = UUID(args["product_id"]) if args.get("product_id") else None
        vid = UUID(args["variant_id"]) if args.get("variant_id") else None
    except (ValueError, AttributeError):
        return {"error": "Invalid UUID. Use get_product_candidates / get_variant_candidates first."}
    return await create_lead(tenant_id, conversation.id, pid, vid, db)


async def _handle_select_for_cart(tenant_id, args, state_context, db):
    vid_str = args.get("variant_id", "")
    try:
        vid = UUID(vid_str)
    except (ValueError, AttributeError):
        return {"error": f"Invalid variant_id '{vid_str}'. Use variant_id from state_context."}
    qty = int(args.get("qty", 1))

    # GUARD: variant_id must exist in state_context (from get_variant_candidates)
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
    n = len(cart)
    w = "товар" if n % 10 == 1 and n % 100 != 11 else "товара" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "товаров"
    return {"status": "added", "cart": cart, "message": f"Добавлено в корзину ({n} {w})"}


def _handle_remove_from_cart(args, state_context):
    vid_str = args.get("variant_id", "")
    cart = state_context.get("cart", [])

    if vid_str == "all":
        state_context["cart"] = []
        return {"status": "cleared", "cart": [], "message": "Корзина очищена"}

    new_cart = []
    removed = None
    for item in cart:
        if item["variant_id"] == vid_str:
            removed = item
        else:
            new_cart.append(item)

    if not removed:
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


async def _handle_create_order_draft(tenant_id, args, conversation, state_context, db):
    # Validate phone number
    phone = (args.get("phone") or "").strip()
    phone_digits = "".join(c for c in phone if c.isdigit())
    if len(phone_digits) < 9 or "XXXX" in phone.upper() or phone_digits == "0" * len(phone_digits):
        return {"error": "Номер телефона обязателен! Спроси у клиента реальный номер телефона. Не придумывай номер."}

    # Normalize phone to +998XXXXXXXXX format
    if phone_digits.startswith("998") and len(phone_digits) == 12:
        phone = f"+{phone_digits}"
    elif len(phone_digits) == 9:
        phone = f"+998{phone_digits}"
    elif phone_digits.startswith("8") and len(phone_digits) == 10:
        phone = f"+998{phone_digits[1:]}"
    else:
        phone = f"+{phone_digits}" if not phone.startswith("+") else phone
    args["phone"] = phone

    # Validate customer name
    customer_name = (args.get("customer_name") or "").strip()
    if len(customer_name) < 2:
        return {"error": "Имя клиента обязательно! Спроси имя."}
    customer_name = " ".join(w.capitalize() for w in customer_name.split())
    args["customer_name"] = customer_name

    # Validate city
    city = (args.get("city") or "").strip()
    if not city:
        return {"error": "Город не указан! Спроси у клиента город доставки. Доступные города: Ташкент, Самарканд, Бухара, Фергана, Наманган, Андижан, Нукус, Карши, Навои, Джизак, Ургенч, Термез."}

    # Check delivery options — if multiple, delivery_type is required
    delivery_type = (args.get("delivery_type") or "").strip()
    if city and not delivery_type:
        del_check = await get_delivery_options(tenant_id, city, db)
        if del_check.get("found") and len(del_check.get("options", [])) > 1:
            opts = [f"{o['delivery_type']} — {o['price']} {o.get('currency','UZS')}, {o['eta']}" for o in del_check["options"]]
            return {
                "error": f"Для города {city} доступно несколько вариантов доставки. Спроси у клиента какой выбирает: {'; '.join(opts)}. Передай delivery_type в create_order_draft.",
                "delivery_options": del_check["options"],
            }

    # Get items from cart
    cart = state_context.get("cart", [])
    logger.info("create_order_draft: cart has %d items: %s", len(cart), [i.get("title", "?") for i in cart])
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

    # Update lead with customer data
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
        delivery_type=args.get("delivery_type"),
    )

    # Clear cart and reset proactive suggestion on success
    if result.get("order_id"):
        state_context["cart"] = []
        state_context.pop("_proactive_suggested", None)

    return result


async def _handle_customer_history(tenant_id, conversation, state_context, db):
    from src.ai.truth_tools import get_customer_history
    result = await get_customer_history(tenant_id, conversation.id, db)
    if result.get("found"):
        state_context["customer"] = {
            "name": result.get("customer_name"),
            "phone": result.get("phone"),
            "city": result.get("city"),
            "address": result.get("address"),
        }
    return result


async def _handle_check_order_status(tenant_id, args, conversation, db, ai_settings):
    from src.ai.truth_tools import check_order_status
    result = await check_order_status(
        tenant_id, conversation.id, args.get("order_number"), db,
    )
    if result.get("found"):
        if result.get("status"):
            status = result["status"]
            result["allowed_actions"] = get_allowed_actions(status, ai_settings)
            result["can_cancel"] = can_cancel_order(status, ai_settings)
            result["can_edit"] = can_edit_order(status, ai_settings)
        elif result.get("orders"):
            for order in result["orders"]:
                status = order.get("status", "")
                order["allowed_actions"] = get_allowed_actions(status, ai_settings)
    return result


async def _handle_add_item_to_order(tenant_id, args, conversation, db):
    from src.ai.truth_tools import add_item_to_order
    try:
        vid = UUID(args["variant_id"])
    except (ValueError, AttributeError):
        return {"error": "Invalid variant_id. Use get_variant_candidates first."}
    return await add_item_to_order(
        tenant_id, conversation.id, args["order_number"],
        vid, int(args.get("qty", 1)), db,
    )


async def _handle_remove_item_from_order(tenant_id, args, conversation, db):
    from src.ai.truth_tools import remove_item_from_order
    try:
        vid = UUID(args["variant_id"])
    except (ValueError, AttributeError):
        return {"error": "Invalid variant_id. Use check_order_status to see order items."}
    return await remove_item_from_order(
        tenant_id, conversation.id, args["order_number"],
        vid, int(args["qty"]) if args.get("qty") else None, db,
    )


async def _handle_request_handoff(tenant_id, args, conversation, state_context, db, ai_settings):
    import re as _re
    from src.handoffs.models import Handoff
    from src.ai.truth_tools import _normalize_order_number

    reason = args.get("reason", "").lower()
    linked_order_num = args.get("linked_order_number")

    # Try to detect order number from reason
    order_to_check = linked_order_num
    if not order_to_check:
        ord_match = _re.search(r'(?:ORD[- ]?)?([A-Fa-f0-9]{8})', reason)
        if ord_match:
            order_to_check = ord_match.group(0)

    # Guard: check if handoff is actually needed for order-related reasons
    if order_to_check and any(kw in reason for kw in ["изменить", "изменен", "edit", "добавить", "убрать", "удалить", "отменить", "cancel"]):
        from src.orders.models import Order as _Order
        ord_result = await db.execute(
            select(_Order).where(
                _Order.tenant_id == tenant_id,
                _Order.order_number == _normalize_order_number(order_to_check),
            )
        )
        order = ord_result.scalar_one_or_none()
        if order:
            if order.status in AI_EDITABLE_STATUSES:
                needs_operator = ai_settings and ai_settings.require_operator_for_edit
                is_cancel = any(kw in reason for kw in ["отменить", "cancel"])
                if is_cancel and order.status == "draft" and ai_settings and not ai_settings.allow_ai_cancel_draft:
                    needs_operator = True
                if not needs_operator:
                    return {
                        "status": "handoff_rejected",
                        "reason": f'Заказ {order.order_number} в статусе "{order.status}" — ты можешь изменить его сам! Используй add_item_to_order или remove_item_from_order. НЕ вызывай request_handoff для этого заказа.',
                        "order_number": order.order_number,
                        "order_status": order.status,
                        "use_tools": ["add_item_to_order", "remove_item_from_order", "cancel_order"],
                    }
            if order.status in LOCKED_STATUSES:
                from src.ai.policies import STATUS_LABELS_RU
                status_label = STATUS_LABELS_RU.get(order.status, order.status)
                return {
                    "status": "handoff_rejected",
                    "reason": f'Заказ {order.order_number} в статусе "{status_label}" — изменения невозможны. Оператор тоже не может помочь. Просто скажи клиенту что изменить нельзя.',
                    "order_number": order.order_number,
                    "order_status": order.status,
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
        n = len(cart)
        w = "товар" if n % 10 == 1 and n % 100 != 11 else "товара" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "товаров"
        summary_parts.append(f"Корзина: {n} {w}")
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
