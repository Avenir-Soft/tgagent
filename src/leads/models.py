import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, UpdatableMixin


class Lead(PkMixin, TenantMixin, UpdatableMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_tenant_status", "tenant_id", "status"),
        CheckConstraint("status IN ('new', 'contacted', 'qualified', 'converted', 'lost')", name="ck_leads_status"),
        CheckConstraint("source IN ('dm', 'comment', 'manual', 'instagram_dm', 'instagram_comment')", name="ck_leads_source"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    interested_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    interested_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'new'")
    )  # new, contacted, qualified, converted, lost
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'dm'")
    )  # dm, comment, manual
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Instagram fields
    instagram_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instagram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
