"""Add timezone/currency to ai_settings, resolution_notes to handoffs, usage_count to templates.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-01 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_settings", sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Tashkent"))
    op.add_column("ai_settings", sa.Column("currency", sa.String(10), nullable=False, server_default="UZS"))
    op.add_column("handoffs", sa.Column("resolution_notes", sa.Text(), nullable=True))
    op.add_column("comment_templates", sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("comment_templates", "usage_count")
    op.drop_column("handoffs", "resolution_notes")
    op.drop_column("ai_settings", "currency")
    op.drop_column("ai_settings", "timezone")
