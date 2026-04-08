from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr

VALID_ROLES = Literal["super_admin", "store_owner", "operator"]


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: VALID_ROLES = "store_owner"


class UserOut(BaseModel):
    id: UUID
    tenant_id: UUID
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
