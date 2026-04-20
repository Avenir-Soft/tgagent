from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CommentTemplateCreate(BaseModel):
    trigger_type: str  # keyword, emoji, regex
    trigger_patterns: list[str]
    language: str = "ru"
    template_text: str
    platform: str = "all"  # all, telegram, instagram


class CommentTemplateOut(BaseModel):
    id: UUID
    tenant_id: UUID
    trigger_type: str
    trigger_patterns: list | dict
    language: str
    template_text: str
    is_active: bool
    usage_count: int = 0
    platform: str = "all"

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: UUID
    tenant_id: UUID
    telegram_chat_id: int
    telegram_user_id: int
    telegram_username: str | None = None
    telegram_first_name: str | None = None
    source_type: str
    source_post_id: int | None
    status: str
    state: str
    state_context: dict | None
    assigned_to_user_id: UUID | None
    ai_enabled: bool
    is_training_candidate: bool = False
    last_message_at: datetime | None
    current_product_id: UUID | None
    current_variant_id: UUID | None
    created_at: datetime
    # Instagram fields
    instagram_user_id: str | None = None
    instagram_thread_id: str | None = None
    # Computed: platform derived from instagram_user_id presence
    source_platform: str = "telegram"

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    telegram_message_id: int | None
    direction: str
    sender_type: str
    raw_text: str | None
    ai_generated: bool
    training_label: str | None = None
    rejection_reason: str | None = None
    rejection_selected_text: str | None = None
    delivery_status: str
    media_type: str | None = None
    media_file_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageEdit(BaseModel):
    raw_text: str
    sync_telegram: bool = False


class MessageSend(BaseModel):
    raw_text: str
    sync_telegram: bool = True


class CommentTemplateUpdate(BaseModel):
    trigger_type: str | None = None
    trigger_patterns: list[str] | None = None
    language: str | None = None
    template_text: str | None = None
    is_active: bool | None = None
    platform: str | None = None


class TrainingLabelUpdate(BaseModel):
    label: str | None = None  # "approved" | "rejected" | null
    reason: str | None = None
    selected_text: str | None = None


class BulkDeleteRequest(BaseModel):
    conversation_ids: list[UUID]


class BroadcastRequest(BaseModel):
    text: str
    filter: str = "all"  # "all" | "ordered"
    max_recipients: int = 2000
    image_url: str | None = None
    scheduled_at: str | None = None  # ISO datetime string for scheduled broadcast
    conversation_ids: list[str] | None = None  # optional: send only to these conversations
