"""Add analytics tables: customer_segments and competitor_prices.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-31 04:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # customer_segments
    op.create_table(
        "customer_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("recency_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("frequency", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monetary", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("r_score", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("f_score", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("m_score", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rfm_score", sa.Integer(), nullable=False, server_default="111"),
        sa.Column("segment", sa.String(30), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_customer_segments_tenant_lead", "customer_segments", ["tenant_id", "lead_id"], unique=True)
    op.create_index("ix_customer_segments_tenant_id", "customer_segments", ["tenant_id"])

    # competitor_prices
    op.create_table(
        "competitor_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("competitor_name", sa.String(255), nullable=False),
        sa.Column("competitor_channel", sa.String(255), nullable=True),
        sa.Column("product_title", sa.String(500), nullable=False),
        sa.Column("competitor_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("our_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default="'UZS'"),
        sa.Column("source", sa.String(30), nullable=False, server_default="'manual'"),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_competitor_prices_tenant_product", "competitor_prices", ["tenant_id", "product_id"])
    op.create_index("ix_competitor_prices_tenant_id", "competitor_prices", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("competitor_prices")
    op.drop_table("customer_segments")
