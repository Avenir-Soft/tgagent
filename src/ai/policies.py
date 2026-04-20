"""Policy layer — codified business rules for AI agent decisions.

These functions return deterministic answers: can/cannot do X given current state.
The AI agent uses these to decide actions without hallucinating rules.

Adapted for Easy Tour — tour booking policies.
"""


# Booking statuses where AI can directly modify
AI_EDITABLE_STATUSES = {"draft", "pending_payment"}
CANCELLABLE_STATUSES = {"draft", "pending_payment"}

# Statuses where changes are impossible (final states)
LOCKED_STATUSES = {"confirmed", "completed", "cancelled"}

STATUS_LABELS = {
    "draft": "Qoralama",
    "pending_payment": "To'lov kutilmoqda",
    "confirmed": "Tasdiqlangan",
    "completed": "Yakunlangan",
    "cancelled": "Bekor qilindi",
}

STATUS_LABELS_RU = {
    "draft": "Черновик",
    "pending_payment": "Ожидает оплаты",
    "confirmed": "Подтверждён",
    "completed": "Завершён",
    "cancelled": "Отменён",
}

STATUS_LABELS_UZ_CYR = {
    "draft": "Қоралама",
    "pending_payment": "Тўлов кутилмоқда",
    "confirmed": "Тасдиқланган",
    "completed": "Якунланган",
    "cancelled": "Бекор қилинди",
}

STATUS_LABELS_EN = {
    "draft": "Draft",
    "pending_payment": "Pending payment",
    "confirmed": "Confirmed",
    "completed": "Completed",
    "cancelled": "Cancelled",
}

_STATUS_LABELS_BY_LANG = {
    "uz_latin": STATUS_LABELS,
    "uz_cyrillic": STATUS_LABELS_UZ_CYR,
    "ru": STATUS_LABELS_RU,
    "en": STATUS_LABELS_EN,
}


def get_status_label(status: str, lang: str = "uz_latin") -> str:
    """Return localized booking status label."""
    labels = _STATUS_LABELS_BY_LANG.get(lang, STATUS_LABELS)
    return labels.get(status, status)


def can_cancel_order(status: str, ai_settings=None) -> dict:
    """Check if booking can be cancelled by customer."""
    if status in CANCELLABLE_STATUSES:
        if status == "draft":
            if ai_settings and not ai_settings.allow_ai_cancel_draft:
                return {"allowed": True, "needs_operator": True, "message": "Operatorni chaqiraman bekor qilish uchun"}
            return {"allowed": True, "needs_operator": False, "message": None}
        # pending_payment — customer can cancel directly, no operator needed
        return {"allowed": True, "needs_operator": False, "message": None}
    return {
        "allowed": False,
        "needs_operator": False,
        "message": f"Buyurtma \"{STATUS_LABELS.get(status, status)}\" holatida — bekor qilish mumkin emas",
    }


def can_edit_order(status: str, ai_settings=None) -> dict:
    """Check if booking can be edited by customer."""
    if status in AI_EDITABLE_STATUSES:
        if ai_settings and ai_settings.require_operator_for_edit:
            return {"allowed": True, "needs_operator": True, "message": "Operatorni chaqiraman o'zgartirish uchun"}
        return {"allowed": True, "needs_operator": False, "message": None}
    return {
        "allowed": False,
        "needs_operator": False,
        "message": f"Buyurtma \"{STATUS_LABELS.get(status, status)}\" holatida — o'zgartirish mumkin emas",
    }


def get_allowed_actions(status: str, ai_settings=None) -> list[str]:
    """Return list of actions available for given booking status."""
    actions = ["check_status"]
    if status in CANCELLABLE_STATUSES:
        actions.append("cancel")
    if status in AI_EDITABLE_STATUSES:
        if ai_settings and ai_settings.require_operator_for_edit:
            actions.append("edit_via_operator")
        else:
            actions.append("edit")
    return actions


# Conversation state transitions based on tool calls
STATE_AFTER_TOOL = {
    "list_categories": "browsing",
    "get_product_candidates": "browsing",
    "get_variant_candidates": "selection",
    "create_order_draft": "pending_payment",
    "check_order_status": "post_order",
    "cancel_order": "post_order",
    "request_handoff": "handoff",
}


def next_state(current_state: str, tool_name: str) -> str:
    """Determine next conversation state after a tool call."""
    return STATE_AFTER_TOOL.get(tool_name, current_state)
