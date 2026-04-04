"""consolidate schema: manual columns, CHECK constraints, FK indexes

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-31 12:00:00.000000

DB-1: Bring 8 manually-added columns under Alembic control.
DB-2: Add CHECK constraints on all status/enum columns.
DB-3: Add indexes on FK columns that lacked them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── DB-1: columns previously added via ALTER TABLE in main.py ──
    # messages
    op.add_column('messages', sa.Column('training_label', sa.String(20), nullable=True), if_not_exists=True)
    op.add_column('messages', sa.Column('rejection_reason', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('messages', sa.Column('rejection_selected_text', sa.Text(), nullable=True), if_not_exists=True)
    # conversations
    op.add_column('conversations', sa.Column('is_training_candidate', sa.Boolean(), server_default=sa.text('false'), nullable=False), if_not_exists=True)
    # ai_settings
    op.add_column('ai_settings', sa.Column('operator_telegram_username', sa.String(100), nullable=True), if_not_exists=True)
    op.add_column('ai_settings', sa.Column('channel_cta_handle', sa.String(100), nullable=True), if_not_exists=True)
    op.add_column('ai_settings', sa.Column('channel_ai_replies_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False), if_not_exists=True)
    op.add_column('ai_settings', sa.Column('channel_show_price', sa.Boolean(), server_default=sa.text('true'), nullable=False), if_not_exists=True)

    # ── DB-1: indexes previously created in main.py ──
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_settings_tenant ON ai_settings (tenant_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_tenant_variant ON inventory (tenant_id, variant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversations_last_msg ON conversations (last_message_at DESC NULLS LAST)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversations_training ON conversations (is_training_candidate) WHERE is_training_candidate = TRUE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversations_state ON conversations (state)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_lead ON orders (lead_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_conv_created ON messages (conversation_id, created_at DESC)")

    # ── DB-2: Fix legacy role values before adding CHECK constraints ──
    op.execute("UPDATE users SET role = 'super_admin' WHERE role = 'admin'")
    op.execute("UPDATE users SET role = 'store_owner' WHERE role = 'owner'")

    # ── Fix legacy trigger_type values before adding CHECK constraints ──
    op.execute("UPDATE comment_templates SET trigger_type = 'keyword' WHERE trigger_type NOT IN ('keyword', 'emoji', 'regex')")

    # ── CHECK constraints on status/enum columns ──
    _checks = [
        ("tenants", "status", ["active", "suspended", "onboarding"]),
        ("users", "role", ["super_admin", "store_owner", "operator"]),
        ("conversations", "status", ["active", "handoff", "closed"]),
        ("conversations", "state", ["idle", "browsing", "selection", "cart", "checkout", "post_order", "handoff"]),
        ("messages", "direction", ["inbound", "outbound"]),
        ("messages", "sender_type", ["customer", "ai", "human_admin", "system"]),
        ("messages", "delivery_status", ["sent", "delivered", "failed"]),
        ("orders", "status", ["draft", "confirmed", "processing", "shipped", "delivered", "cancelled"]),
        ("leads", "status", ["new", "contacted", "qualified", "converted", "lost"]),
        ("leads", "source", ["dm", "comment", "manual"]),
        ("handoffs", "priority", ["low", "normal", "high", "urgent"]),
        ("handoffs", "status", ["pending", "assigned", "resolved"]),
        ("telegram_accounts", "status", ["pending", "connected", "disconnected", "error"]),
        ("comment_templates", "trigger_type", ["keyword", "emoji", "regex"]),
        ("delivery_rules", "delivery_type", ["courier", "post", "pickup"]),
    ]
    for table, col, values in _checks:
        vals = ", ".join(f"'{v}'" for v in values)
        name = f"ck_{table}_{col}"
        # Use raw SQL for idempotent "IF NOT EXISTS"-style
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({col} IN ({vals}))"
        )
    # training_label is nullable so allow NULL
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS ck_messages_training_label")
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT ck_messages_training_label "
        "CHECK (training_label IS NULL OR training_label IN ('approved', 'rejected'))"
    )

    # ── DB-3: FK indexes for JOIN performance ──
    _fk_indexes = [
        ("ix_handoffs_conversation_id", "handoffs", "conversation_id"),
        ("ix_handoffs_assigned_to", "handoffs", "assigned_to_user_id"),
        ("ix_handoffs_linked_order", "handoffs", "linked_order_id"),
        ("ix_categories_parent_id", "categories", "parent_id"),
        ("ix_products_category_id", "products", "category_id"),
        ("ix_product_media_variant_id", "product_media", "variant_id"),
        ("ix_telegram_channels_discussion", "telegram_channels", "linked_discussion_group_id"),
        ("ix_conversations_assigned_to", "conversations", "assigned_to_user_id"),
    ]
    for name, table, col in _fk_indexes:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})")


def downgrade() -> None:
    # Drop FK indexes
    _fk_indexes = [
        "ix_handoffs_conversation_id", "ix_handoffs_assigned_to", "ix_handoffs_linked_order",
        "ix_categories_parent_id", "ix_products_category_id", "ix_product_media_variant_id",
        "ix_telegram_channels_discussion", "ix_conversations_assigned_to",
    ]
    for name in _fk_indexes:
        op.execute(f"DROP INDEX IF EXISTS {name}")

    # Drop CHECK constraints
    _tables_cols = [
        "ck_tenants_status", "ck_users_role", "ck_conversations_status", "ck_conversations_state",
        "ck_messages_direction", "ck_messages_sender_type", "ck_messages_delivery_status",
        "ck_messages_training_label", "ck_orders_status", "ck_leads_status", "ck_leads_source",
        "ck_handoffs_priority", "ck_handoffs_status", "ck_telegram_accounts_status",
        "ck_comment_templates_trigger_type", "ck_delivery_rules_delivery_type",
    ]
    for name in _tables_cols:
        table = name.split("_", 2)[1]  # ck_TABLE_col
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")

    # Drop startup indexes
    for name in ["uq_ai_settings_tenant", "uq_inventory_tenant_variant", "ix_conversations_last_msg",
                 "ix_conversations_training", "ix_conversations_state", "ix_orders_lead", "ix_messages_conv_created"]:
        op.execute(f"DROP INDEX IF EXISTS {name}")

    # Drop columns (DB-1)
    op.drop_column('ai_settings', 'channel_show_price')
    op.drop_column('ai_settings', 'channel_ai_replies_enabled')
    op.drop_column('ai_settings', 'channel_cta_handle')
    op.drop_column('ai_settings', 'operator_telegram_username')
    op.drop_column('conversations', 'is_training_candidate')
    op.drop_column('messages', 'rejection_selected_text')
    op.drop_column('messages', 'rejection_reason')
    op.drop_column('messages', 'training_label')
