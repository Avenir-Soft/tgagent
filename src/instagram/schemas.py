"""Pydantic schemas for Instagram integration."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class InstagramAccountOut(BaseModel):
    id: UUID
    tenant_id: UUID
    instagram_user_id: str
    instagram_username: str | None = None
    display_name: str | None = None
    facebook_page_id: str | None = None
    status: str
    is_primary: bool
    token_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InstagramConnectRequest(BaseModel):
    access_token: str
    instagram_user_id: str | None = None


class InstagramWebhookVerify(BaseModel):
    hub_mode: str
    hub_verify_token: str
    hub_challenge: str
