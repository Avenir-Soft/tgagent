import logging
import uuid
from uuid import UUID as PyUUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.models import PkMixin, TenantMixin, TimestampMixin


class AuditLog(PkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # user, ai, system
    actor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


async def log_audit(
    db: AsyncSession,
    tenant_id: PyUUID,
    actor_type: str,  # "user", "ai", "system"
    actor_id: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    meta_json: dict | None = None,
):
    """Fire-and-forget audit log entry."""
    try:
        entry = AuditLog(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            meta_json=meta_json,
        )
        db.add(entry)
        # Don't flush here — let the caller's transaction handle it
    except Exception:
        logging.getLogger(__name__).warning("Audit log failed", exc_info=True)
