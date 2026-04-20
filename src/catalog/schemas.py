from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# --- Products ---
class ProductCreate(BaseModel):
    name: str = Field(max_length=500)
    slug: str | None = Field(None, max_length=500)
    description: str | None = None
    category_id: UUID | None = None
    brand: str | None = Field(None, max_length=200)
    model: str | None = Field(None, max_length=200)
    external_id: str | None = Field(None, max_length=100)
    variants: list["VariantCreate"] | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category_id: UUID | None = None
    brand: str | None = None
    model: str | None = None
    is_active: bool | None = None


class VariantBriefOut(BaseModel):
    id: UUID
    title: str
    sku: str | None
    color: str | None
    storage: str | None
    ram: str | None
    size: str | None
    attributes_json: dict | None = None
    price: Decimal
    currency: str
    is_active: bool
    stock: int = 0
    reserved: int = 0

    model_config = {"from_attributes": True}


class ProductOut(BaseModel):
    id: UUID
    tenant_id: UUID
    external_id: str | None
    name: str
    slug: str
    description: str | None
    category_id: UUID | None
    brand: str | None
    model: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductDetailOut(ProductOut):
    variants: list[VariantBriefOut] = []
    aliases: list["ProductAliasOut"] = []
    total_stock: int = 0
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    category_name: str | None = None
    image_url: str | None = None

    model_config = {"from_attributes": True}


# --- Variants ---
class VariantCreate(BaseModel):
    title: str
    sku: str | None = None
    color: str | None = None
    storage: str | None = None
    ram: str | None = None
    size: str | None = None
    attributes_json: dict | None = None
    price: Decimal
    currency: str = "UZS"


class VariantUpdate(BaseModel):
    title: str | None = None
    sku: str | None = None
    color: str | None = None
    storage: str | None = None
    ram: str | None = None
    size: str | None = None
    attributes_json: dict | None = None
    price: Decimal | None = None
    currency: str | None = None
    is_active: bool | None = None


class VariantOut(BaseModel):
    id: UUID
    tenant_id: UUID
    product_id: UUID
    title: str
    sku: str | None
    color: str | None
    storage: str | None
    ram: str | None
    size: str | None
    attributes_json: dict | None
    price: Decimal
    currency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Inventory ---
class InventoryUpdate(BaseModel):
    quantity: int
    reserved_quantity: int = 0


class InventoryOut(BaseModel):
    id: UUID
    tenant_id: UUID
    variant_id: UUID
    quantity: int
    reserved_quantity: int
    available_quantity: int
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Delivery Rules ---
class DeliveryRuleCreate(BaseModel):
    city: str | None = None
    zone: str | None = None
    delivery_type: str
    price: Decimal
    eta_min_days: int = 1
    eta_max_days: int = 3
    cod_available: bool = False
    pickup_available: bool = False


class DeliveryRuleUpdate(BaseModel):
    city: str | None = None
    zone: str | None = None
    delivery_type: str | None = None
    price: Decimal | None = None
    eta_min_days: int | None = None
    eta_max_days: int | None = None
    cod_available: bool | None = None
    pickup_available: bool | None = None


class DeliveryRuleOut(BaseModel):
    id: UUID
    tenant_id: UUID
    city: str | None
    zone: str | None
    delivery_type: str
    price: Decimal
    eta_min_days: int
    eta_max_days: int
    cod_available: bool
    pickup_available: bool
    is_active: bool

    model_config = {"from_attributes": True}


# --- Categories ---
class CategoryCreate(BaseModel):
    name: str
    slug: str
    parent_id: UUID | None = None


class CategoryOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    parent_id: UUID | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Product Aliases ---
class ProductAliasCreate(BaseModel):
    alias_text: str
    priority: int = 0


class ProductAliasOut(BaseModel):
    id: UUID
    tenant_id: UUID
    product_id: UUID
    alias_text: str
    priority: int
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Product Media ---
class ProductMediaCreate(BaseModel):
    variant_id: UUID | None = None
    url: str
    media_type: str = "photo"
    sort_order: int = 0


class ProductMediaOut(BaseModel):
    id: UUID
    tenant_id: UUID
    product_id: UUID
    variant_id: UUID | None
    url: str
    media_type: str
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}
