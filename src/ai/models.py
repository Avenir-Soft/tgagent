import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, UpdatableMixin


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
