"""Consolidate all startup DDL into Alembic.

Moves all raw DDL from main.py _run_startup_migrations() into a proper
Alembic revision. This is the single source of truth for schema.

Revision ID: 78ebf771026b
Revises: e5f6a7b8c9d0
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '78ebf771026b'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = [
    "users", "telegram_accounts", "telegram_channels",
    "telegram_discussion_groups", "categories", "products",
    "product_aliases", "product_variants", "inventory",
    "product_media", "delivery_rules", "customer_segments",
    "competitor_prices", "leads", "handoffs", "audit_logs",
    "ai_settings", "ai_trace_logs", "orders",
    "comment_templates", "conversations", "messages",
    "broadcast_history",
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── Columns ──────────────────────────────────────────────────────────
    cols = [
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS training_label VARCHAR(20)",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_training_candidate BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS rejection_selected_text TEXT",
        "ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS operator_telegram_username VARCHAR(100)",
        "ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS channel_cta_handle VARCHAR(100)",
        "ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS channel_ai_replies_enabled BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE ai_settings ADD COLUMN IF NOT EXISTS channel_show_price BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_type VARCHAR(20)",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_file_id VARCHAR(255)",
        "ALTER TABLE broadcast_history ADD COLUMN IF NOT EXISTS recipients_json JSONB",
        "ALTER TABLE broadcast_history ADD COLUMN IF NOT EXISTS target_conversation_ids JSONB",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500)",
        "ALTER TABLE ai_trace_logs ADD COLUMN IF NOT EXISTS prompt_tokens INT NOT NULL DEFAULT 0",
        "ALTER TABLE ai_trace_logs ADD COLUMN IF NOT EXISTS completion_tokens INT NOT NULL DEFAULT 0",
    ]
    for s in cols:
        try:
            conn.execute(sa.text(s))
        except Exception:
            pass

    # ── Drop old global unique indexes (replaced by per-tenant) ──────────
    for s in [
        "DROP INDEX IF EXISTS orders_order_number_key",
        "DROP INDEX IF EXISTS users_email_key",
    ]:
        try:
            conn.execute(sa.text(s))
        except Exception:
            pass

    # ── Indexes ──────────────────────────────────────────────────────────
    idxs = [
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_settings_tenant ON ai_settings (tenant_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_tenant_variant ON inventory (tenant_id, variant_id)",
        "CREATE INDEX IF NOT EXISTS ix_conversations_last_msg ON conversations (last_message_at DESC NULLS LAST)",
        "CREATE INDEX IF NOT EXISTS ix_conversations_training ON conversations (is_training_candidate) WHERE is_training_candidate = TRUE",
        "CREATE INDEX IF NOT EXISTS ix_conversations_state ON conversations (state)",
        "CREATE INDEX IF NOT EXISTS ix_orders_lead ON orders (lead_id)",
        "CREATE INDEX IF NOT EXISTS ix_messages_conv_created ON messages (conversation_id, created_at DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_telegram_accounts_tenant_phone ON telegram_accounts (tenant_id, phone_number)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_tenant_order_number ON orders (tenant_id, order_number)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_email ON users (tenant_id, email)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_categories_tenant_slug ON categories (tenant_id, slug)",
        "CREATE INDEX IF NOT EXISTS ix_ai_trace_logs_tenant ON ai_trace_logs (tenant_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_broadcast_history_tenant ON broadcast_history (tenant_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_customer_segments_tenant_lead ON customer_segments (tenant_id, lead_id)",
        "CREATE INDEX IF NOT EXISTS ix_customer_segments_tenant_id ON customer_segments (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_competitor_prices_tenant_product ON competitor_prices (tenant_id, product_id)",
        "CREATE INDEX IF NOT EXISTS ix_competitor_prices_tenant_id ON competitor_prices (tenant_id)",
    ]
    for s in idxs:
        try:
            conn.execute(sa.text(s))
        except Exception:
            pass

    # ── Tables ───────────────────────────────────────────────────────────
    tbls = [
        """CREATE TABLE IF NOT EXISTS customer_segments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL, lead_id UUID NOT NULL,
            customer_name VARCHAR(255), telegram_user_id BIGINT NOT NULL,
            recency_days INT NOT NULL DEFAULT 0, frequency INT NOT NULL DEFAULT 0,
            monetary NUMERIC(14,2) NOT NULL DEFAULT 0,
            r_score INT NOT NULL DEFAULT 1, f_score INT NOT NULL DEFAULT 1,
            m_score INT NOT NULL DEFAULT 1, rfm_score INT NOT NULL DEFAULT 111,
            segment VARCHAR(30) NOT NULL DEFAULT 'new',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        """CREATE TABLE IF NOT EXISTS competitor_prices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            product_id UUID REFERENCES products(id) ON DELETE SET NULL,
            competitor_name VARCHAR(255) NOT NULL, competitor_channel VARCHAR(255),
            product_title VARCHAR(500) NOT NULL,
            competitor_price NUMERIC(14,2) NOT NULL, our_price NUMERIC(14,2),
            currency VARCHAR(10) NOT NULL DEFAULT 'UZS',
            source VARCHAR(30) NOT NULL DEFAULT 'manual',
            captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        """CREATE TABLE IF NOT EXISTS broadcast_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            message_text TEXT NOT NULL, image_url TEXT,
            filter_type VARCHAR(30) NOT NULL,
            sent_count INT NOT NULL DEFAULT 0, failed_count INT NOT NULL DEFAULT 0,
            total_targets INT NOT NULL DEFAULT 0,
            status VARCHAR(30) NOT NULL DEFAULT 'sending',
            scheduled_at TIMESTAMPTZ, sent_at TIMESTAMPTZ,
            created_by_user_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        """CREATE TABLE IF NOT EXISTS ai_trace_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            conversation_id UUID, trace_id VARCHAR(8) NOT NULL,
            user_message TEXT NOT NULL DEFAULT '', detected_language VARCHAR(20) NOT NULL DEFAULT '',
            model VARCHAR(50) NOT NULL DEFAULT '',
            state_before VARCHAR(30) NOT NULL DEFAULT '', state_after VARCHAR(30) NOT NULL DEFAULT '',
            tools_called JSONB NOT NULL DEFAULT '[]'::jsonb,
            steps JSONB NOT NULL DEFAULT '[]'::jsonb,
            final_response TEXT NOT NULL DEFAULT '',
            image_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
            total_duration_ms INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
    ]
    for s in tbls:
        try:
            conn.execute(sa.text(s))
        except Exception:
            pass

    # ── Row-Level Security ───────────────────────────────────────────────
    for tbl in _RLS_TABLES:
        try:
            conn.execute(sa.text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY"))
        except Exception:
            pass
        try:
            conn.execute(sa.text(f"""DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = '{tbl}' AND policyname = 'tenant_isolation'
                ) THEN
                    EXECUTE 'CREATE POLICY tenant_isolation ON {tbl} USING (tenant_id = current_setting(''app.current_tenant_id'', true)::uuid)';
                END IF;
            END $$"""))
        except Exception:
            pass

    # ── Legacy role migration ────────────────────────────────────────────
    try:
        result = conn.execute(sa.text("SELECT COUNT(*) FROM users WHERE role IN ('admin', 'owner')"))
        if result.scalar():
            conn.execute(sa.text("UPDATE users SET role = 'super_admin' WHERE role = 'admin'"))
            conn.execute(sa.text("UPDATE users SET role = 'store_owner' WHERE role = 'owner'"))
    except Exception:
        pass


def downgrade() -> None:
    conn = op.get_bind()
    for tbl in _RLS_TABLES:
        try:
            conn.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}"))
            conn.execute(sa.text(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY"))
        except Exception:
            pass
