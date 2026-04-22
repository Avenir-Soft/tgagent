from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    name: str
    slug: str


class TenantUpdate(BaseModel):
    name: str | None = None
    status: str | None = None


class TenantOut(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    updated_at: datetime
    products_count: int = 0
    conversations_count: int = 0
    users_count: int = 0
    orders_count: int = 0
    revenue_total: float = 0.0
    variants_count: int = 0
    # Telegram agent info (detail only)
    telegram_phone: str | None = None
    telegram_username: str | None = None
    telegram_display_name: str | None = None
    telegram_status: str | None = None
    # AI config (detail only)
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_language: str | None = None
    ai_tone: str | None = None
    # Activity chart (detail only)
    activity_30d: list[dict] = []
    # Monitoring fields (detail only)
    tenant_created_days_ago: int = 0
    last_message_at: str | None = None
    total_messages: int = 0

    model_config = {"from_attributes": True}


class TenantListOut(BaseModel):
    items: list[TenantOut]
    total: int


class BulkStatusRequest(BaseModel):
    tenant_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    status: Literal["active", "suspended"]
