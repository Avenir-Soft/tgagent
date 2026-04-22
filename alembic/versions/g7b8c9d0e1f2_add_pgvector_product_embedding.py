"""Add pgvector extension and product embedding column.

Enables hybrid search: vector (semantic) + ILIKE (exact).

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-20 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Enable pgvector extension (requires superuser or CREATE privilege)
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        # Extension may already exist or require manual creation by DBA
        pass

    # Add embedding column
    conn.execute(sa.text(
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS embedding vector(1536)"
    ))

    # HNSW index for fast cosine similarity search
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_products_embedding "
        "ON products USING hnsw (embedding vector_cosine_ops)"
    ))


def downgrade() -> None:
    op.drop_index("ix_products_embedding", table_name="products")
    op.drop_column("products", "embedding")
