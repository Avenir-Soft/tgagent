"""Tests that PolicyConfig overrides actually affect business decisions.

These tests verify the fix for the bug where load_policy_config() existed
but was never called — meaning AiSettings toggles in the admin UI had
ZERO effect on AI behavior.

The fix: orchestrator.py now loads PolicyConfig once per request and passes
it through _execute_tool -> truth_tools -> policy functions.
"""

import pytest

from src.ai.policies import (
    PolicyConfig,
    can_cancel_order,
    can_edit_order,
    get_allowed_actions,
)


# ── Scenario: Admin disables AI draft cancellation ───────────────────────

class TestAdminDisablesAiCancelDraft:
    """When allow_ai_cancel_draft=False, even draft orders need operator."""

    def test_draft_without_config_ai_can_cancel(self):
        """Default: AI cancels drafts directly."""
        result = can_cancel_order("draft")
        assert result["allowed"] is True
        assert result["needs_operator"] is False

    def test_draft_with_config_disabled_needs_operator(self):
        """Override: draft cancel requires operator."""
        config = PolicyConfig(allow_ai_cancel_draft=False)
        result = can_cancel_order("draft", config)
        assert result["allowed"] is True
        assert result["needs_operator"] is True
        assert "оператор" in result["message"].lower()

    def test_allowed_actions_shows_cancel_via_operator(self):
        """Actions list reflects operator requirement."""
        config = PolicyConfig(allow_ai_cancel_draft=False)
        actions = get_allowed_actions("draft", config)
        assert "cancel_via_operator" in actions
        assert "cancel" not in actions

    def test_confirmed_still_needs_operator_regardless(self):
        """Confirmed orders always need operator, config doesn't matter."""
        for config in [None, PolicyConfig(), PolicyConfig(allow_ai_cancel_draft=False)]:
            result = can_cancel_order("confirmed", config)
            assert result["needs_operator"] is True

    def test_locked_statuses_unaffected(self):
        """Shipped/delivered/cancelled never cancellable, config irrelevant."""
        config = PolicyConfig(allow_ai_cancel_draft=False)
        for status in ("shipped", "delivered", "cancelled"):
            result = can_cancel_order(status, config)
            assert result["allowed"] is False


# ── Scenario: Admin requires operator for ALL edits ──────────────────────

class TestAdminRequiresOperatorForEdit:
    """When require_operator_for_edit=True, even draft/confirmed need operator."""

    def test_draft_without_config_ai_can_edit(self):
        """Default: AI edits drafts directly."""
        result = can_edit_order("draft")
        assert result["allowed"] is True
        assert result["needs_operator"] is False

    def test_draft_with_config_needs_operator(self):
        """Override: draft edit requires operator."""
        config = PolicyConfig(require_operator_for_edit=True)
        result = can_edit_order("draft", config)
        assert result["allowed"] is True
        assert result["needs_operator"] is True

    def test_confirmed_with_config_needs_operator(self):
        """Override: confirmed edit requires operator."""
        config = PolicyConfig(require_operator_for_edit=True)
        result = can_edit_order("confirmed", config)
        assert result["allowed"] is True
        assert result["needs_operator"] is True

    def test_allowed_actions_shows_edit_via_operator(self):
        """Actions list reflects operator requirement for both statuses."""
        config = PolicyConfig(require_operator_for_edit=True)
        for status in ("draft", "confirmed"):
            actions = get_allowed_actions(status, config)
            assert "edit_via_operator" in actions
            assert "edit" not in actions

    def test_processing_always_needs_operator(self):
        """Processing always needs operator regardless of config."""
        for config in [None, PolicyConfig(), PolicyConfig(require_operator_for_edit=True)]:
            result = can_edit_order("processing", config)
            assert result["needs_operator"] is True

    def test_locked_always_blocked(self):
        """Locked statuses can't be edited regardless of config."""
        config = PolicyConfig(require_operator_for_edit=True)
        for status in ("shipped", "delivered", "cancelled"):
            result = can_edit_order(status, config)
            assert result["allowed"] is False


# ── Scenario: Combined config overrides ──────────────────────────────────

class TestCombinedConfigOverrides:
    """Multiple settings changed at once."""

    def test_both_cancel_and_edit_require_operator(self):
        config = PolicyConfig(
            allow_ai_cancel_draft=False,
            require_operator_for_edit=True,
        )
        # Draft cancel → operator
        cancel = can_cancel_order("draft", config)
        assert cancel["needs_operator"] is True
        # Draft edit → operator
        edit = can_edit_order("draft", config)
        assert edit["needs_operator"] is True
        # Actions reflect both
        actions = get_allowed_actions("draft", config)
        assert "cancel_via_operator" in actions
        assert "edit_via_operator" in actions
        assert "cancel" not in actions
        assert "edit" not in actions

    def test_default_config_matches_no_config(self):
        """PolicyConfig() with defaults == passing None."""
        default = PolicyConfig()
        for status in ("draft", "confirmed", "processing", "shipped", "delivered", "cancelled"):
            assert can_cancel_order(status, default) == can_cancel_order(status, None)
            assert can_edit_order(status, default) == can_edit_order(status, None)
            assert get_allowed_actions(status, default) == get_allowed_actions(status, None)

    def test_config_does_not_affect_locked_statuses(self):
        """No config combination can unlock shipped/delivered/cancelled."""
        config = PolicyConfig(
            allow_ai_cancel_draft=True,
            require_operator_for_edit=False,
        )
        for status in ("shipped", "delivered", "cancelled"):
            assert can_cancel_order(status, config)["allowed"] is False
            assert can_edit_order(status, config)["allowed"] is False


# ── Verify config parameter actually reaches policy functions ────────────

class TestConfigParameterWiring:
    """Ensure the config parameter is properly accepted and used."""

    def test_can_cancel_order_accepts_config_kwarg(self):
        """Function signature accepts config as keyword arg."""
        result = can_cancel_order("draft", config=PolicyConfig(allow_ai_cancel_draft=False))
        assert result["needs_operator"] is True

    def test_can_edit_order_accepts_config_kwarg(self):
        result = can_edit_order("draft", config=PolicyConfig(require_operator_for_edit=True))
        assert result["needs_operator"] is True

    def test_get_allowed_actions_accepts_config_kwarg(self):
        actions = get_allowed_actions("draft", config=PolicyConfig(allow_ai_cancel_draft=False))
        assert "cancel_via_operator" in actions

    def test_can_cancel_order_accepts_config_positional(self):
        """Also works as positional arg (how orchestrator calls it)."""
        config = PolicyConfig(allow_ai_cancel_draft=False)
        result = can_cancel_order("draft", config)
        assert result["needs_operator"] is True

    def test_can_edit_order_accepts_config_positional(self):
        config = PolicyConfig(require_operator_for_edit=True)
        result = can_edit_order("draft", config)
        assert result["needs_operator"] is True
