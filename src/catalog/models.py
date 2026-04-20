import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, TimestampMixin, UpdatableMixin


class Category(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_categories_tenant_slug"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_ru: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_uz_cyr: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    parent = relationship("Category", remote_side="Category.id", lazy="selectin")
    products = relationship("Product", back_populates="category", lazy="noload")


class Product(PkMixin, TenantMixin, UpdatableMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_tenant_active", "tenant_id", "is_active"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    name_ru: Mapped[str | None] = mapped_column(String(500), nullable=True)
    name_uz_cyr: Mapped[str | None] = mapped_column(String(500), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(500), nullable=True)
    slug: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    category = relationship("Category", back_populates="products")
    variants = relationship("ProductVariant", back_populates="product", lazy="selectin")
    aliases = relationship("ProductAlias", back_populates="product", lazy="selectin")
    media = relationship("ProductMedia", back_populates="product", lazy="selectin")


class ProductAlias(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "product_aliases"
    __table_args__ = (
        Index("ix_product_aliases_tenant_alias", "tenant_id", "alias_text"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias_text: Mapped[str] = mapped_column(String(300), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    product = relationship("Product", back_populates="aliases")


class ProductVariant(PkMixin, TenantMixin, UpdatableMixin, Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        Index("ix_product_variants_tenant_product_active", "tenant_id", "product_id", "is_active"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ram: Mapped[str | None] = mapped_column(String(50), nullable=True)
    size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    attributes_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'UZS'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    product = relationship("Product", back_populates="variants")
    inventory = relationship("Inventory", back_populates="variant", lazy="selectin")
    media = relationship("ProductMedia", back_populates="variant", lazy="selectin")


class Inventory(PkMixin, TenantMixin, UpdatableMixin, Base):
    __tablename__ = "inventory"
    __table_args__ = (
        Index("ix_inventory_tenant_variant", "tenant_id", "variant_id"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventory_reserved_non_negative"),
        CheckConstraint("reserved_quantity <= quantity", name="ck_inventory_reserved_lte_quantity"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    variant = relationship("ProductVariant", back_populates="inventory")

    @property
    def available_quantity(self) -> int:
        return self.quantity - self.reserved_quantity


class ProductMedia(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "product_media"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'photo'")
    )  # photo, video, document
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    product = relationship("Product", back_populates="media")
    variant = relationship("ProductVariant", back_populates="media")


class DeliveryRule(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "delivery_rules"
    __table_args__ = (
        Index("ix_delivery_rules_tenant_city_active", "tenant_id", "city", "is_active"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_type: Mapped[str] = mapped_column(String(50), nullable=False)  # courier, post, pickup
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    eta_min_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    eta_max_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    cod_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    pickup_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
