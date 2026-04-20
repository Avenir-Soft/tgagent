"""Instagram account model for Meta Graph API integration."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, UpdatableMixin


class InstagramAccount(PkMixin, TenantMixin, UpdatableMixin, Base):
    """Instagram Business account connected per tenant via Meta Graph API."""

    __tablename__ = "instagram_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "instagram_user_id", name="uq_instagram_accounts_tenant_user"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instagram_user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    instagram_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    facebook_page_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'disconnected'")
    )  # connected, disconnected, token_expired
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    tenant = relationship("Tenant")
