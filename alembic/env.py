import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.core.config import settings
from src.core.database import Base

# Import all models so they register with Base.metadata
from src.tenants.models import Tenant  # noqa
from src.auth.models import User  # noqa
from src.telegram.models import TelegramAccount, TelegramChannel, TelegramDiscussionGroup  # noqa
from src.catalog.models import Product, ProductVariant, Inventory, DeliveryRule  # noqa
from src.conversations.models import CommentTemplate, Conversation, Message  # noqa
from src.leads.models import Lead  # noqa
from src.orders.models import Order, OrderItem  # noqa
from src.handoffs.models import Handoff  # noqa
from src.ai.models import AiSettings  # noqa
from src.core.audit import AuditLog  # noqa

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
