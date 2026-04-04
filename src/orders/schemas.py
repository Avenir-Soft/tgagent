from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class OrderItemCreate(BaseModel):
    product_id: UUID
    product_variant_id: UUID | None = None
    qty: int = 1
    unit_price: Decimal
    total_price: Decimal


class OrderCreate(BaseModel):
    lead_id: UUID | None = None
    customer_name: str
    phone: str
    city: str | None = None
    address: str | None = None
    delivery_type: str | None = None
    payment_type: str | None = None
    currency: str = "UZS"
    items: list[OrderItemCreate]


class OrderUpdate(BaseModel):
    status: str | None = None
    address: str | None = None
    delivery_type: str | None = None
    payment_type: str | None = None


class OrderItemOut(BaseModel):
    id: UUID
    product_id: UUID | None
    product_variant_id: UUID | None
    product_name: str | None = None
    variant_title: str | None = None
    qty: int
    unit_price: Decimal
    total_price: Decimal

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: UUID
    tenant_id: UUID
    lead_id: UUID | None
    order_number: str
    customer_name: str
    phone: str
    city: str | None
    address: str | None
    delivery_type: str | None
    payment_type: str | None
    total_amount: Decimal
    currency: str
    status: str
    items: list[OrderItemOut]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
