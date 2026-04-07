import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, TimestampMixin


class CommentTemplate(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "comment_templates"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # keyword, emoji, regex
    trigger_patterns: Mapped[dict] = mapped_column(
        JSONB, nullable=False
    )  # ["+" , "цена", "сколько", ...]
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'ru'")
    )
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Conversation(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_tenant_chat", "tenant_id", "telegram_chat_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # dm, comment_thread, manual
    source_post_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'active'")
    )  # active, handoff, closed
    state: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'NEW_CHAT'")
    )  # DM state machine
    state_context: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # product_id, variant_id, city, etc.
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_training_candidate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    current_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True
    )

    messages = relationship("Message", back_populates="conversation", lazy="noload")


class Message(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_tenant_conversation_created", "tenant_id", "conversation_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    direction: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # inbound, outbound
    sender_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # customer, ai, human_admin
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # photo, sticker, gif, voice, video_note, video, document
    media_file_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Telegram file ID for downloading
    ai_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    delivery_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'sent'")
    )  # sent, delivered, failed
    training_label: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # approved, rejected
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_selected_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    conversation = relationship("Conversation", back_populates="messages")
