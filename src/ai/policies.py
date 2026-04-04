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
LOCKED_STATUSES = {"shipped", "delivered", "cancelled"}

STATUS_LABELS_RU = {
    "draft": "Ожидает подтверждения",
    "confirmed": "Подтверждён",
    "processing": "В обработке",
    "shipped": "Отправлен",
    "delivered": "Доставлен",
    "cancelled": "Отменён",
}


def can_cancel_order(status: str) -> dict:
    """Check if order can be cancelled by customer."""
    if status in CANCELLABLE_STATUSES:
        if status == "draft":
            return {"allowed": True, "needs_operator": False, "message": None}
        return {"allowed": True, "needs_operator": True, "message": "Заказ подтверждён — подключу оператора для отмены"}
    return {
        "allowed": False,
        "needs_operator": False,
        "message": f"Заказ в статусе \"{STATUS_LABELS_RU.get(status, status)}\" — отмена невозможна",
    }


def can_edit_order(status: str) -> dict:
    """Check if order can be edited by customer."""
    if status in AI_EDITABLE_STATUSES:
        return {"allowed": True, "needs_operator": False, "message": None}
    if status in OPERATOR_REQUIRED_STATUSES:
        return {"allowed": True, "needs_operator": True, "message": "Заказ в обработке — подключу оператора для изменений"}
    return {
        "allowed": False,
        "needs_operator": False,
        "message": f"Заказ в статусе \"{STATUS_LABELS_RU.get(status, status)}\" — изменения невозможны",
    }


def get_allowed_actions(status: str) -> list[str]:
    """Return list of actions available for given order status."""
    actions = ["check_status"]
    if status in CANCELLABLE_STATUSES:
        actions.append("cancel")
    if status in AI_EDITABLE_STATUSES:
        actions.append("edit")
    if status in OPERATOR_REQUIRED_STATUSES:
        actions.append("edit_via_operator")
    if status == "delivered":
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
}


def next_state(current_state: str, tool_name: str) -> str:
    """Determine next conversation state after a tool call."""
    return STATE_AFTER_TOOL.get(tool_name, current_state)
