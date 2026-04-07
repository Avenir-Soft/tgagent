from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class OrderItemCreate(BaseModel):
    product_id: UUID
    product_variant_id: UUID | None = None
    qty: int = Field(default=1, ge=1, le=9999)
    unit_price: Decimal = Field(ge=0)
    total_price: Decimal = Field(ge=0)


class OrderCreate(BaseModel):
    lead_id: UUID | None = None
    customer_name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=3, max_length=30)
    city: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    delivery_type: str | None = Field(default=None, max_length=50)
    payment_type: str | None = Field(default=None, max_length=50)
    currency: str = Field(default="UZS", max_length=10)
    items: list[OrderItemCreate] = Field(min_length=1)

    @field_validator("customer_name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("customer_name cannot be blank")
        return v.strip()


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
    conversation_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
