import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, TimestampMixin, UpdatableMixin


class AiSettings(PkMixin, TenantMixin, UpdatableMixin, Base):
    __tablename__ = "ai_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tone: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'friendly_sales'")
    )
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'ru'")
    )
    fallback_mode: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'handoff'")
    )  # handoff, fallback_model
    allow_auto_comment_reply: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    allow_auto_dm_reply: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    require_handoff_for_unknown_product: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    # Order policies
    allow_ai_cancel_draft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )  # AI can cancel draft orders without operator
    require_operator_for_edit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )  # Always require operator for order edits
    require_operator_for_returns: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )  # Always require operator for returns/exchanges

    # AI behavior policies
    max_variants_in_reply: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )  # Max variants to show in one message
    confirm_before_order: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )  # Require confirmation before creating order
    auto_handoff_on_profanity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )  # Auto-handoff on first profanity (vs 2nd message)

    # Operator notifications
    operator_telegram_username: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    # Channel comment auto-responses
    channel_cta_handle: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    channel_ai_replies_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    channel_show_price: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    # Per-tenant AI provider configuration
    ai_provider: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'openai'")
    )  # "openai" | "anthropic"
    ai_api_key_encrypted: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Fernet-encrypted API key (never exposed to frontend)
    ai_model_override: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Override model per tenant (e.g. "gpt-4o", "claude-sonnet-4-6")


class AITraceLog(PkMixin, TenantMixin, TimestampMixin, Base):
    """Persistent AI trace log — stores full pipeline trace for each AI interaction."""
    __tablename__ = "ai_trace_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
    )
    trace_id: Mapped[str] = mapped_column(String(8), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    detected_language: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("''"))
    model: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("''"))
    state_before: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("''"))
    state_after: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("''"))
    tools_called: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    final_response: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    image_urls: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    total_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
