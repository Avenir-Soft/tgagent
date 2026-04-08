"""Policy layer — codified business rules for AI agent decisions.

These functions return deterministic answers: can/cannot do X given current state.
The AI agent uses these to decide actions without hallucinating rules.
"""


# Order statuses where AI can directly modify the order
AI_EDITABLE_STATUSES = {"draft", "confirmed"}
CANCELLABLE_STATUSES = {"draft", "confirmed"}

# Statuses where changes need operator (in progress)
OPERATOR_REQUIRED_STATUSES = {"processing"}

# Statuses where changes are impossible (final states)
LOCKED_STATUSES = {"shipped", "delivered", "cancelled", "returned"}

# Statuses eligible for return request
RETURNABLE_STATUSES = {"delivered"}

STATUS_LABELS_RU = {
    "draft": "Ожидает подтверждения",
    "confirmed": "Подтверждён",
    "processing": "В обработке",
    "shipped": "Отправлен",
    "delivered": "Доставлен",
    "cancelled": "Отменён",
    "returned": "Возвращён",
}


def can_cancel_order(status: str, ai_settings=None) -> dict:
    """Check if order can be cancelled by customer.

    Respects ai_settings.allow_ai_cancel_draft when provided.
    """
    if status in CANCELLABLE_STATUSES:
        if status == "draft":
            # Check if AI is allowed to cancel drafts without operator
            if ai_settings and not ai_settings.allow_ai_cancel_draft:
                return {"allowed": True, "needs_operator": True, "message": "Подключу оператора для отмены заказа"}
            return {"allowed": True, "needs_operator": False, "message": None}
        return {"allowed": True, "needs_operator": True, "message": "Заказ подтверждён — подключу оператора для отмены"}
    return {
        "allowed": False,
        "needs_operator": False,
        "message": f"Заказ в статусе \"{STATUS_LABELS_RU.get(status, status)}\" — отмена невозможна",
    }


def can_edit_order(status: str, ai_settings=None) -> dict:
    """Check if order can be edited by customer.

    Respects ai_settings.require_operator_for_edit when provided.
    """
    if status in AI_EDITABLE_STATUSES:
        # Check if operator is always required for edits
        if ai_settings and ai_settings.require_operator_for_edit:
            return {"allowed": True, "needs_operator": True, "message": "Подключу оператора для изменения заказа"}
        return {"allowed": True, "needs_operator": False, "message": None}
    if status in OPERATOR_REQUIRED_STATUSES:
        return {"allowed": True, "needs_operator": True, "message": "Заказ в обработке — подключу оператора для изменений"}
    return {
        "allowed": False,
        "needs_operator": False,
        "message": f"Заказ в статусе \"{STATUS_LABELS_RU.get(status, status)}\" — изменения невозможны",
    }


RETURN_WINDOW_DAYS = 14  # Days after delivery when returns are still accepted


def can_return_order(status: str, ai_settings=None, delivered_at=None) -> dict:
    """Check if order is eligible for a return request.

    Returns are only possible for delivered orders within RETURN_WINDOW_DAYS.
    By default (or when require_operator_for_returns=True), always routes to operator.
    """
    if status not in RETURNABLE_STATUSES:
        reason = STATUS_LABELS_RU.get(status, status)
        if status in ("draft", "confirmed", "processing", "shipped"):
            return {"allowed": False, "needs_operator": False,
                    "message": f"Заказ в статусе \"{reason}\" — можно отменить, но не вернуть. Для отмены используй cancel_order."}
        return {"allowed": False, "needs_operator": False,
                "message": f"Заказ в статусе \"{reason}\" — возврат невозможен"}

    # Check return window (if delivery date is known)
    if delivered_at:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if delivered_at.tzinfo is None:
            delivered_at = delivered_at.replace(tzinfo=timezone.utc)
        days_since = (now - delivered_at).days
        if days_since > RETURN_WINDOW_DAYS:
            return {"allowed": False, "needs_operator": False,
                    "message": f"Срок возврата ({RETURN_WINDOW_DAYS} дней) истёк. Заказ доставлен {days_since} дней назад."}

    # Delivered — return is possible
    if ai_settings and not getattr(ai_settings, "require_operator_for_returns", True):
        # AI can process return directly (future: auto-return flow)
        return {"allowed": True, "needs_operator": False, "message": None}
    # Default: always require operator for returns
    return {"allowed": True, "needs_operator": True,
            "message": "Для оформления возврата подключу оператора"}


def get_allowed_actions(status: str, ai_settings=None) -> list[str]:
    """Return list of actions available for given order status."""
    actions = ["check_status"]
    if status in CANCELLABLE_STATUSES:
        # If cancel not allowed by AI for drafts, still show cancel but it will route to operator
        actions.append("cancel")
    if status in AI_EDITABLE_STATUSES:
        if ai_settings and ai_settings.require_operator_for_edit:
            actions.append("edit_via_operator")
        else:
            actions.append("edit")
    if status in OPERATOR_REQUIRED_STATUSES:
        actions.append("edit_via_operator")
    if status in RETURNABLE_STATUSES:
        actions.append("return_request")
    return actions


# Conversation state transitions based on tool calls
STATE_AFTER_TOOL = {
    "list_categories": "browsing",
    "get_product_candidates": "browsing",
    "get_variant_candidates": "selection",
    "select_for_cart": "cart",
    "remove_from_cart": "cart",
    "create_order_draft": "post_order",
    "check_order_status": "post_order",
    "cancel_order": "post_order",
    "add_item_to_order": "post_order",
    "remove_item_from_order": "post_order",
    "request_handoff": "handoff",
    "request_return": "post_order",
}


def next_state(current_state: str, tool_name: str) -> str:
    """Determine next conversation state after a tool call."""
    return STATE_AFTER_TOOL.get(tool_name, current_state)
