from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator


class AiSettingsCreate(BaseModel):
    tone: str = "friendly_sales"
    language: str = "ru"
    fallback_mode: str = "handoff"
    allow_auto_comment_reply: bool = True
    allow_auto_dm_reply: bool = True
    require_handoff_for_unknown_product: bool = True
    # Order policies
    allow_ai_cancel_draft: bool = True
    require_operator_for_edit: bool = True
    require_operator_for_returns: bool = True
    # AI behavior policies
    max_variants_in_reply: int = 5
    confirm_before_order: bool = True
    auto_handoff_on_profanity: bool = False
    # Operator notifications
    operator_telegram_username: str | None = None
    # Channel comment auto-responses
    channel_cta_handle: str | None = None
    channel_ai_replies_enabled: bool = True
    channel_show_price: bool = True
    # Store-level settings
    timezone: str | None = "Asia/Tashkent"
    currency: str | None = "UZS"
    # Prompt rules
    prompt_rules: list[dict[str, Any]] | None = None


class AiSettingsOut(BaseModel):
    id: UUID
    tenant_id: UUID
    tone: str
    language: str
    fallback_mode: str
    allow_auto_comment_reply: bool
    allow_auto_dm_reply: bool
    require_handoff_for_unknown_product: bool
    # Order policies
    allow_ai_cancel_draft: bool
    require_operator_for_edit: bool
    require_operator_for_returns: bool
    # AI behavior policies
    max_variants_in_reply: int
    confirm_before_order: bool
    auto_handoff_on_profanity: bool
    # Operator notifications
    operator_telegram_username: str | None = None
    # Channel comment auto-responses
    channel_cta_handle: str | None = None
    channel_ai_replies_enabled: bool = True
    channel_show_price: bool = True
    # Store-level settings
    timezone: str | None = "Asia/Tashkent"
    currency: str | None = "UZS"
    # Prompt rules
    prompt_rules: list[dict[str, Any]] | None = None
    # Per-tenant AI provider (never expose the actual key)
    ai_provider: str = "openai"
    has_api_key: bool = False
    ai_model_override: str | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _compute_has_api_key(cls, data):
        """Compute has_api_key from the ORM model's ai_api_key_encrypted field."""
        if hasattr(data, "__dict__"):
            # SQLAlchemy model object
            encrypted = getattr(data, "ai_api_key_encrypted", None)
            # We need to set has_api_key on the dict form — Pydantic v2 from_attributes
            # The trick: return a dict with the computed field injected
            d = {}
            for field_name in cls.model_fields:
                if field_name == "has_api_key":
                    d["has_api_key"] = bool(encrypted)
                else:
                    d[field_name] = getattr(data, field_name, None)
            return d
        # Already a dict
        if isinstance(data, dict):
            encrypted = data.get("ai_api_key_encrypted")
            data["has_api_key"] = bool(encrypted)
        return data


class ApiKeyInput(BaseModel):
    provider: str  # "openai" | "anthropic"
    api_key: str
    model: str | None = None


class ApiKeyStatusOut(BaseModel):
    has_key: bool
    provider: str
    model: str | None = None
