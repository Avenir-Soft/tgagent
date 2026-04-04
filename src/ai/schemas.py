from typing import Any
from uuid import UUID

from pydantic import BaseModel


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
    timezone: str = "Asia/Tashkent"
    currency: str = "UZS"
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
    timezone: str = "Asia/Tashkent"
    currency: str = "UZS"
    # Prompt rules
    prompt_rules: list[dict[str, Any]] | None = None

    model_config = {"from_attributes": True}
