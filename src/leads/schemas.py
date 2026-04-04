from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LeadCreate(BaseModel):
    conversation_id: UUID | None = None
    customer_name: str | None = None
    telegram_user_id: int
    phone: str | None = None
    city: str | None = None
    interested_product_id: UUID | None = None
    interested_variant_id: UUID | None = None
    source: str = "dm"


class LeadUpdate(BaseModel):
    customer_name: str | None = None
    phone: str | None = None
    city: str | None = None
    status: str | None = None


class LeadOut(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID | None
    customer_name: str | None
    telegram_user_id: int
    telegram_username: str | None
    phone: str | None
    city: str | None
    interested_product_id: UUID | None
    interested_variant_id: UUID | None
    status: str
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
