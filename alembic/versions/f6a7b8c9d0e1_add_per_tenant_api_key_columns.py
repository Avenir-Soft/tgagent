"""add per-tenant API key columns to ai_settings

Revision ID: f6a7b8c9d0e1
Revises: 78ebf771026b
Create Date: 2026-04-20 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "78ebf771026b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_settings",
        sa.Column("ai_provider", sa.String(20), server_default=sa.text("'openai'"), nullable=False),
    )
    op.add_column(
        "ai_settings",
        sa.Column("ai_api_key_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "ai_settings",
        sa.Column("ai_model_override", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_settings", "ai_model_override")
    op.drop_column("ai_settings", "ai_api_key_encrypted")
    op.drop_column("ai_settings", "ai_provider")
