"""Tool executor — dispatches AI tool calls to truth_tools and handles guards.

Each tool gets validated inputs, guard checks, and enriched results.
Adapted for Easy Tour — tour booking tools.
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

    elif name == "create_order_draft":
        return await _handle_create_order_draft(tenant_id, args, conversation, state_context, db)

    elif name == "get_customer_history":
        return await _handle_customer_history(tenant_id, conversation, state_context, db)

    elif name == "check_order_status":
        return await _handle_check_order_status(tenant_id, args, conversation, state_context, db, ai_settings)

    elif name == "cancel_order":
        from src.ai.truth_tools import cancel_order_by_number
        return await cancel_order_by_number(
            tenant_id, conversation.id, args["order_number"], db, ai_settings=ai_settings,
        )

    elif name == "request_handoff":
        return await _handle_request_handoff(tenant_id, args, conversation, state_context, db, ai_settings)

    # Legacy tool names — return helpful error
    elif name in ("get_delivery_options", "select_for_cart", "remove_from_cart",
                   "add_item_to_order", "remove_item_from_order", "request_return"):
        return {"error": f"Tool '{name}' is not available for tour bookings."}

    elif name == "get_variant_price":
        from src.ai.truth_tools import get_variant_price
        try:
            vid = UUID(args["variant_id"])
        except (ValueError, AttributeError):
            return {"error": "Invalid variant_id"}
        return await get_variant_price(tenant_id, vid, db)

    elif name == "get_variant_stock":
        from src.ai.truth_tools import get_variant_stock
        try:
            vid = UUID(args["variant_id"])
        except (ValueError, AttributeError):
            return {"error": "Invalid variant_id"}
        return await get_variant_stock(tenant_id, vid, db)

    else:
        return {"error": f"Unknown tool: {name}"}


# ──────────────────────────────────────────────
# Individual tool handlers
# ──────────────────────────────────────────────


async def _handle_product_candidates(tenant_id, args, db, ai_settings):
    result = await get_product_candidates(tenant_id, args["query"], db)
    if ai_settings and ai_settings.require_handoff_for_unknown_product:
        if not result.get("found"):
            result["_handoff_hint"] = "Tur topilmadi. request_handoff orqali operatorni chaqir."
    return result


async def _handle_variant_candidates(tenant_id, args, db, ai_settings):
    try:
        pid = UUID(args["product_id"])
    except (ValueError, AttributeError):
        return {"error": f"Invalid product_id '{args.get('product_id')}'. Use get_product_candidates first."}
    result = await get_variant_candidates(tenant_id, pid, db)
    if ai_settings and result.get("found") and result.get("variants"):
        max_v = ai_settings.max_variants_in_reply or 5
        variants = result["variants"]
        if len(variants) > max_v:
            result["variants"] = variants[:max_v]
            result["total_variants"] = len(variants)
            result["showing"] = max_v
            result["note"] = f"{max_v} ta sanadan {len(variants)} ta ko'rsatildi."
    return result


async def _handle_create_order_draft(tenant_id, args, conversation, state_context, db):
    # Validate phone number
    phone = (args.get("phone") or "").strip()
    phone_digits = "".join(c for c in phone if c.isdigit())
    if len(phone_digits) < 9 or "XXXX" in phone.upper() or phone_digits == "0" * len(phone_digits):
        return {"error": "Telefon raqami kerak! Mijozdan haqiqiy telefon raqamini so'rang."}

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
        return {"error": "Ism kerak! Mijozdan ismini so'rang."}
    customer_name = " ".join(w.capitalize() for w in customer_name.split())
    args["customer_name"] = customer_name

    # Get selected tour variant from state_context
    # For tours: one booking = one tour date, qty = num_participants
    num_participants = int(args.get("num_participants", 1))
    if num_participants < 1:
        num_participants = 1

    # 1. Use variant_id from LLM args (preferred — LLM picks the right one)
    variant_id = args.get("variant_id")

    # 2. Fallback: booking context
    if not variant_id:
        booking = state_context.get("booking", {})
        if booking.get("variant_id"):
            variant_id = booking["variant_id"]

    # 3. Last fallback: first variant from state_context products
    if not variant_id:
        products = state_context.get("products", {})
        for prod_info in products.values():
            for v in prod_info.get("variants", []):
                variant_id = v.get("variant_id")
                break
            if variant_id:
                break

    if not variant_id:
        return {"error": "Tur sanasi tanlanmagan. Avval get_variant_candidates chaqirib, mijozga sanalarni ko'rsating."}

    variant_ids = [UUID(variant_id)]
    quantities = [num_participants]

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
        lead_obj.status = "converted"

    result = await create_order_draft(
        tenant_id, lead_id, variant_ids, quantities,
        args.get("customer_name", ""),
        args.get("phone", ""),
        None,  # no city for tours
        None,  # no address for tours
        db,
    )

    # Clear booking context on success
    if result.get("order_id"):
        state_context.pop("booking", None)
        state_context.pop("_proactive_suggested", None)

    return result


async def _handle_customer_history(tenant_id, conversation, state_context, db):
    from src.ai.truth_tools import get_customer_history
    result = await get_customer_history(tenant_id, conversation.id, db)
    if result.get("found"):
        state_context["customer"] = {
            "name": result.get("customer_name"),
            "phone": result.get("phone"),
        }
    return result


async def _handle_check_order_status(tenant_id, args, conversation, state_context, db, ai_settings):
    from src.ai.truth_tools import check_order_status
    result = await check_order_status(
        tenant_id, conversation.id, args.get("order_number"), db,
        state_context=state_context,
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


async def _handle_request_handoff(tenant_id, args, conversation, state_context, db, ai_settings):
    import re as _re
    from src.handoffs.models import Handoff
    from src.ai.truth_tools import _normalize_order_number

    reason = args.get("reason", "").lower()
    linked_order_num = args.get("linked_order_number")

    # Try to detect booking number from reason
    order_to_check = linked_order_num
    if not order_to_check:
        ord_match = _re.search(r'(?:BK[- ]?)?([A-Fa-f0-9]{8})', reason)
        if ord_match:
            order_to_check = ord_match.group(0)

    # Guard: check if handoff is actually needed for booking-related reasons
    if order_to_check and any(kw in reason for kw in ["изменить", "edit", "отменить", "cancel", "o'zgartir", "bekor"]):
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
                is_cancel = any(kw in reason for kw in ["отменить", "cancel", "bekor"])
                if is_cancel:
                    return {
                        "status": "handoff_rejected",
                        "reason": f"Buyurtma {order.order_number} bekor qilish mumkin. cancel_order chaqir!",
                        "use_tools": ["cancel_order"],
                    }
            if order.status in LOCKED_STATUSES:
                from src.ai.policies import STATUS_LABELS
                status_label = STATUS_LABELS.get(order.status, order.status)
                return {
                    "status": "handoff_rejected",
                    "reason": f'Buyurtma {order.order_number} "{status_label}" holatida — o\'zgartirish mumkin emas.',
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

    # Build summary
    summary_parts = []
    orders = state_context.get("orders", [])
    if orders:
        summary_parts.append(f"Buyurtmalar: {', '.join(o.get('order_number', '?') for o in orders)}")

    handoff = Handoff(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        reason=args.get("reason", "AI requested handoff"),
        priority=args.get("priority", "normal"),
        summary="; ".join(summary_parts) if summary_parts else None,
        linked_order_id=linked_order_id,
    )
    db.add(handoff)
    conversation.status = "handoff"
    conversation.ai_enabled = False
    await db.flush()

    # Notify operator via Telegram
    try:
        from src.ai.orchestrator import _notify_operator_handoff
        reason_text = args.get("reason", "Handoff")
        customer = conversation.telegram_first_name or "Mijoz"
        notify_msg = f"🔔 Handoff: {customer}\n\n{reason_text}"
        await _notify_operator_handoff(tenant_id, conversation.id, notify_msg, ai_settings)
    except Exception:
        pass  # non-fatal

    # SSE notification for frontend
    try:
        from src.sse.event_bus import publish_event
        await publish_event(f"sse:{tenant_id}:tenant", {
            "event": "conversation_updated",
            "conversation_id": str(conversation.id),
            "state": "handoff",
            "reason": args.get("reason", ""),
        })
    except Exception:
        pass

    return {"status": "handoff_created", "reason": args.get("reason")}
