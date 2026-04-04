from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HandoffCreate(BaseModel):
    conversation_id: UUID
    reason: str
    priority: str = "normal"


class HandoffUpdate(BaseModel):
    status: str | None = None
    assigned_to_user_id: UUID | None = None
    resolution_notes: str | None = None


class HandoffOut(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    reason: str
    summary: str | None = None
    priority: str
    status: str
    assigned_to_user_id: UUID | None
    assigned_to_user_name: str | None = None
    linked_order_id: UUID | None = None
    linked_order_number: str | None = None
    conversation_name: str | None = None
    resolution_notes: str | None = None
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}
