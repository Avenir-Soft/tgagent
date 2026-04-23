"""Add timezone and currency columns to ai_settings.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-20 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_settings",
        sa.Column("timezone", sa.String(50), nullable=True, server_default=sa.text("'Asia/Tashkent'")),
    )
    op.add_column(
        "ai_settings",
        sa.Column("currency", sa.String(10), nullable=True, server_default=sa.text("'UZS'")),
    )


def downgrade() -> None:
    op.drop_column("ai_settings", "currency")
    op.drop_column("ai_settings", "timezone")
