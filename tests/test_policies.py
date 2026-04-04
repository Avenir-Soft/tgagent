"""Unit tests for src/ai/policies.py — PolicyConfig, can_cancel_order,
can_edit_order, get_allowed_actions, next_state."""

import pytest

from src.ai.policies import (
    AI_EDITABLE_STATUSES,
    CANCELLABLE_STATUSES,
    LOCKED_STATUSES,
    OPERATOR_REQUIRED_STATUSES,
    STATE_AFTER_TOOL,
    PolicyConfig,
    can_cancel_order,
    can_edit_order,
    get_allowed_actions,
    next_state,
)


# ── can_cancel_order ─────────────────────────────────────────────────────────

class TestCanCancelOrder:
    def test_draft_default(self):
        result = can_cancel_order("draft")
        assert result["allowed"] is True
        assert result["needs_operator"] is False
        assert result["message"] is None

    def test_confirmed(self):
        result = can_cancel_order("confirmed")
        assert result["allowed"] is True
        assert result["needs_operator"] is True
        assert result["message"] is not None

    def test_processing_not_allowed(self):
        result = can_cancel_order("processing")
        assert result["allowed"] is False
        assert result["needs_operator"] is False

    def test_shipped_not_allowed(self):
        result = can_cancel_order("shipped")
        assert result["allowed"] is False

    def test_delivered_not_allowed(self):
        result = can_cancel_order("delivered")
        assert result["allowed"] is False

    def test_cancelled_not_allowed(self):
        result = can_cancel_order("cancelled")
        assert result["allowed"] is False

    def test_draft_with_ai_cancel_disabled(self):
        config = PolicyConfig(allow_ai_cancel_draft=False)
        result = can_cancel_order("draft", config=config)
        assert result["allowed"] is True
        assert result["needs_operator"] is True

    def test_confirmed_unaffected_by_ai_cancel_flag(self):
        config = PolicyConfig(allow_ai_cancel_draft=False)
        result = can_cancel_order("confirmed", config=config)
        assert result["allowed"] is True
        assert result["needs_operator"] is True

    def test_locked_unaffected_by_config(self):
        config = PolicyConfig(allow_ai_cancel_draft=False)
        for status in LOCKED_STATUSES:
            result = can_cancel_order(status, config=config)
            assert result["allowed"] is False

    def test_message_includes_status_label_for_locked(self):
        result = can_cancel_order("shipped")
        assert "Отправлен" in result["message"]

        result = can_cancel_order("delivered")
        assert "Доставлен" in result["message"]

        result = can_cancel_order("cancelled")
        assert "Отменён" in result["message"]


# ── can_edit_order ───────────────────────────────────────────────────────────

class TestCanEditOrder:
    def test_draft_default(self):
        result = can_edit_order("draft")
        assert result["allowed"] is True
        assert result["needs_operator"] is False
        assert result["message"] is None

    def test_confirmed_default(self):
        result = can_edit_order("confirmed")
        assert result["allowed"] is True
        assert result["needs_operator"] is False
        assert result["message"] is None

    def test_processing_needs_operator(self):
        result = can_edit_order("processing")
        assert result["allowed"] is True
        assert result["needs_operator"] is True

    def test_shipped_not_allowed(self):
        result = can_edit_order("shipped")
        assert result["allowed"] is False

    def test_delivered_not_allowed(self):
        result = can_edit_order("delivered")
        assert result["allowed"] is False

    def test_cancelled_not_allowed(self):
        result = can_edit_order("cancelled")
        assert result["allowed"] is False

    def test_draft_with_require_operator_for_edit(self):
        config = PolicyConfig(require_operator_for_edit=True)
        result = can_edit_order("draft", config=config)
        assert result["allowed"] is True
        assert result["needs_operator"] is True

    def test_confirmed_with_require_operator_for_edit(self):
        config = PolicyConfig(require_operator_for_edit=True)
        result = can_edit_order("confirmed", config=config)
        assert result["allowed"] is True
        assert result["needs_operator"] is True

    def test_processing_unaffected_by_require_operator(self):
        config = PolicyConfig(require_operator_for_edit=True)
        result = can_edit_order("processing", config=config)
        assert result["allowed"] is True
        assert result["needs_operator"] is True

    def test_locked_unaffected_by_config(self):
        config = PolicyConfig(require_operator_for_edit=True)
        for status in LOCKED_STATUSES:
            result = can_edit_order(status, config=config)
            assert result["allowed"] is False


# ── get_allowed_actions ──────────────────────────────────────────────────────

class TestGetAllowedActions:
    def test_draft_default(self):
        actions = get_allowed_actions("draft")
        assert "check_status" in actions
        assert "cancel" in actions
        assert "edit" in actions

    def test_confirmed_default(self):
        actions = get_allowed_actions("confirmed")
        assert "check_status" in actions
        assert "cancel" in actions
        assert "edit" in actions

    def test_processing(self):
        actions = get_allowed_actions("processing")
        assert "check_status" in actions
        assert "edit_via_operator" in actions
        assert "cancel" not in actions
        assert "edit" not in actions

    def test_shipped(self):
        actions = get_allowed_actions("shipped")
        assert actions == ["check_status"]

    def test_delivered(self):
        actions = get_allowed_actions("delivered")
        assert "check_status" in actions
        assert "return_request" in actions

    def test_cancelled(self):
        actions = get_allowed_actions("cancelled")
        assert actions == ["check_status"]

    def test_draft_with_ai_cancel_disabled(self):
        config = PolicyConfig(allow_ai_cancel_draft=False)
        actions = get_allowed_actions("draft", config=config)
        assert "cancel_via_operator" in actions
        assert "cancel" not in actions

    def test_confirmed_unaffected_by_ai_cancel_flag(self):
        config = PolicyConfig(allow_ai_cancel_draft=False)
        actions = get_allowed_actions("confirmed", config=config)
        assert "cancel" in actions

    def test_draft_with_require_operator_for_edit(self):
        config = PolicyConfig(require_operator_for_edit=True)
        actions = get_allowed_actions("draft", config=config)
        assert "edit_via_operator" in actions
        assert "edit" not in actions

    def test_confirmed_with_require_operator_for_edit(self):
        config = PolicyConfig(require_operator_for_edit=True)
        actions = get_allowed_actions("confirmed", config=config)
        assert "edit_via_operator" in actions
        assert "edit" not in actions

    def test_all_statuses_include_check_status(self):
        all_statuses = ["draft", "confirmed", "processing", "shipped", "delivered", "cancelled"]
        for status in all_statuses:
            actions = get_allowed_actions(status)
            assert "check_status" in actions, f"check_status missing for {status}"


# ── next_state ───────────────────────────────────────────────────────────────

class TestNextState:
    def test_all_known_tools(self):
        expected = {
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
        for tool, expected_state in expected.items():
            result = next_state("idle", tool)
            assert result == expected_state, f"next_state('idle', '{tool}') = '{result}', expected '{expected_state}'"

    def test_unknown_tool_returns_current(self):
        assert next_state("browsing", "unknown_tool") == "browsing"
        assert next_state("cart", "get_variant_price") == "cart"

    def test_delivery_options_transitions_to_checkout(self):
        assert next_state("idle", "get_delivery_options") == "checkout"
        assert next_state("cart", "get_delivery_options") == "checkout"

    def test_current_state_irrelevant_for_known_tools(self):
        assert next_state("idle", "select_for_cart") == "cart"
        assert next_state("post_order", "select_for_cart") == "cart"
        assert next_state("handoff", "list_categories") == "browsing"

    def test_state_after_tool_matches_constant(self):
        for tool_name, target_state in STATE_AFTER_TOOL.items():
            assert next_state("idle", tool_name) == target_state


# ── PolicyConfig defaults ────────────────────────────────────────────────────

class TestPolicyConfig:
    def test_defaults(self):
        config = PolicyConfig()
        assert config.allow_ai_cancel_draft is True
        assert config.require_operator_for_edit is False
        assert config.require_operator_for_returns is True
        assert config.max_variants_in_reply == 5
        assert config.confirm_before_order is True
        assert config.auto_handoff_on_profanity is False

    def test_override_fields(self):
        config = PolicyConfig(allow_ai_cancel_draft=False, require_operator_for_edit=True)
        assert config.allow_ai_cancel_draft is False
        assert config.require_operator_for_edit is True

    def test_none_config_gives_default_behavior(self):
        result_no_config = can_cancel_order("draft")
        result_default_config = can_cancel_order("draft", config=PolicyConfig())
        assert result_no_config == result_default_config
