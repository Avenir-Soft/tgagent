import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, TimestampMixin


class BroadcastHistory(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "broadcast_history"

    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    filter_type: Mapped[str] = mapped_column(String(30), nullable=False)  # all | ordered
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_targets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="sending"
    )  # sending | sent | scheduled | cancelled | failed
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    # List of recipients: [{name, username, conversation_id, sent}]
    recipients_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Selected conversation IDs (for targeted broadcasts)
    target_conversation_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
