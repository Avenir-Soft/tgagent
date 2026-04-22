"""Pydantic schemas for the Super Admin Platform API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from src.auth.schemas import VALID_ROLES, _validate_password


# ── Stats ─────────────────────────────────────────────────────────────────────

class MessagesByDay(BaseModel):
    date: str
    count: int


class PlatformStats(BaseModel):
    total_tenants: int
    total_users: int
    total_conversations: int
    total_orders: int
    total_messages_24h: int
    total_revenue: float
    orders_24h: int = 0
    revenue_24h: float = 0.0
    tenants_by_status: dict[str, int] = {}
    messages_by_day: list[MessagesByDay] = []
    conversations_by_day: list[MessagesByDay] = []
    orders_by_day: list[MessagesByDay] = []


# ── Users ─────────────────────────────────────────────────────────────────────

class PlatformUserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    tenant_id: UUID
    tenant_name: str | None = None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class PlatformUserListOut(BaseModel):
    items: list[PlatformUserOut]
    total: int


class BulkUserStatusRequest(BaseModel):
    user_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    is_active: bool


class PlatformUserCreate(BaseModel):
    tenant_id: UUID
    email: EmailStr
    full_name: str
    password: str = Field(min_length=8)
    role: VALID_ROLES = "store_owner"

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return _validate_password(v)


class PlatformUserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    role: VALID_ROLES | None = None
    is_active: bool | None = None
    new_password: str | None = None

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_password(v)
        return v


# ── AI Logs ───────────────────────────────────────────────────────────────────

class AITraceLogOut(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_name: str | None = None
    conversation_id: UUID | None = None
    trace_id: str
    user_message: str
    detected_language: str
    model: str
    state_before: str
    state_after: str
    tools_called: list
    total_duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Billing ───────────────────────────────────────────────────────────────────

class TenantBilling(BaseModel):
    tenant_id: UUID
    tenant_name: str
    messages_count: int
    ai_calls_count: int
    orders_count: int
    conversations_count: int
    tokens_total: int = 0
    estimated_cost_usd: float = 0.0


class ModelDistributionItem(BaseModel):
    model: str
    calls: int
    tokens: int
    cost_usd: float


class DailyBillingItem(BaseModel):
    date: str
    ai_calls: int
    messages: int
    tokens: int


# ── Audit Logs ────────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_name: str | None = None
    actor_type: str
    actor_id: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    meta_json: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Platform Settings ─────────────────────────────────────────────────────────

class PlatformSettingsOut(BaseModel):
    default_ai_model: str = "gpt-4o-mini"
    fallback_model: str = "gpt-4o"
    default_language: str = "ru"
    default_timezone: str = "Asia/Tashkent"
    max_products_per_tenant: int = 500
    max_users_per_tenant: int = 10
    max_messages_per_day: int = 5000
    trial_days: int = 14
    signup_enabled: bool = True
    maintenance_mode: bool = False
    read_only_mode: bool = False


class PlatformSettingsUpdate(BaseModel):
    default_ai_model: str | None = None
    fallback_model: str | None = None
    default_language: str | None = None
    default_timezone: str | None = None
    max_products_per_tenant: int | None = None
    max_users_per_tenant: int | None = None
    max_messages_per_day: int | None = None
    trial_days: int | None = None
    signup_enabled: bool | None = None
    maintenance_mode: bool | None = None
    read_only_mode: bool | None = None


# ── Impersonate ───────────────────────────────────────────────────────────────

class ImpersonateResponse(BaseModel):
    access_token: str
    tenant_name: str
    user_email: str
