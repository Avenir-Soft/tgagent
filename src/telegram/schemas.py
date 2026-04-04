from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TelegramAccountCreate(BaseModel):
    phone_number: str
    display_name: str | None = None
    username: str | None = None


class TelegramAccountOut(BaseModel):
    id: UUID
    tenant_id: UUID
    phone_number: str
    display_name: str | None
    username: str | None
    status: str
    is_primary: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TelegramChannelCreate(BaseModel):
    telegram_channel_id: int
    title: str
    username: str | None = None
    linked_discussion_group_id: UUID | None = None


class TelegramChannelOut(BaseModel):
    id: UUID
    tenant_id: UUID
    telegram_channel_id: int
    title: str
    username: str | None
    linked_discussion_group_id: UUID | None
    is_active: bool

    model_config = {"from_attributes": True}


class DiscussionGroupCreate(BaseModel):
    telegram_group_id: int
    title: str


class DiscussionGroupOut(BaseModel):
    id: UUID
    tenant_id: UUID
    telegram_group_id: int
    title: str
    is_active: bool

    model_config = {"from_attributes": True}
