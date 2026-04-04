"""add prompt_rules to ai_settings

Revision ID: a1b2c3d4e5f6
Revises: ddde0bb3d5da
Create Date: 2026-03-30 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ddde0bb3d5da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ai_settings', sa.Column('prompt_rules', JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=True))


def downgrade() -> None:
    op.drop_column('ai_settings', 'prompt_rules')
