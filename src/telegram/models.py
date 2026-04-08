import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, TimestampMixin, UpdatableMixin


class TelegramAccount(PkMixin, TenantMixin, UpdatableMixin, Base):
    """AI admin's Telegram account connected per tenant."""

    __tablename__ = "telegram_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_number", name="uq_telegram_accounts_tenant_phone"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_ref: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # encrypted session string reference
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )  # pending, connected, disconnected, error
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    tenant = relationship("Tenant", back_populates="telegram_accounts")


class TelegramChannel(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "telegram_channels"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    telegram_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    linked_discussion_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_discussion_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class TelegramDiscussionGroup(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "telegram_discussion_groups"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    telegram_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
