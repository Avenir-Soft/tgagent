"""Analytics models — customer segments and competitor prices."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, TimestampMixin, UpdatableMixin


class CustomerSegment(PkMixin, TenantMixin, UpdatableMixin, Base):
    __tablename__ = "customer_segments"
    __table_args__ = (
        Index("ix_customer_segments_tenant_lead", "tenant_id", "lead_id", unique=True),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recency_days: Mapped[int] = mapped_column(nullable=False, default=0)
    frequency: Mapped[int] = mapped_column(nullable=False, default=0)
    monetary: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    r_score: Mapped[int] = mapped_column(nullable=False, default=1)
    f_score: Mapped[int] = mapped_column(nullable=False, default=1)
    m_score: Mapped[int] = mapped_column(nullable=False, default=1)
    rfm_score: Mapped[int] = mapped_column(nullable=False, default=111)
    segment: Mapped[str] = mapped_column(String(30), nullable=False, default="new")


class CompetitorPrice(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "competitor_prices"
    __table_args__ = (
        Index("ix_competitor_prices_tenant_product", "tenant_id", "product_id"),
    )

    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    competitor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    competitor_channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_title: Mapped[str] = mapped_column(String(500), nullable=False)
    competitor_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    our_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="UZS")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )
