import uuid
from datetime import datetime

from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.models import PkMixin, UpdatableMixin


class Tenant(PkMixin, UpdatableMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )  # active, suspended, onboarding

    # relationships
    users = relationship("User", back_populates="tenant", lazy="noload")
    telegram_accounts = relationship("TelegramAccount", back_populates="tenant", lazy="noload")
