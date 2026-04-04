"""Seed script — creates a super admin tenant + user for initial setup."""

import asyncio
import sys

sys.path.insert(0, ".")

from src.core.database import engine, async_session_factory, Base
from src.core.security import hash_password
from src.tenants.models import Tenant
from src.auth.models import User

# Import all models so tables are registered
from src.telegram.models import *  # noqa
from src.catalog.models import *  # noqa
from src.conversations.models import *  # noqa
from src.leads.models import *  # noqa
from src.orders.models import *  # noqa
from src.handoffs.models import *  # noqa
from src.ai.models import *  # noqa
from src.core.audit import *  # noqa


async def seed():
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        # Create platform tenant
        tenant = Tenant(name="AI Closer Platform", slug="platform", status="active")
        db.add(tenant)
        await db.flush()

        # Create super admin user
        admin = User(
            tenant_id=tenant.id,
            full_name="Super Admin",
            email="admin@aicloser.io",
            password_hash=hash_password("admin123"),
            role="super_admin",
        )
        db.add(admin)
        await db.commit()

        print(f"✓ Tenant created: {tenant.name} (id: {tenant.id})")
        print(f"✓ Super admin created: {admin.email}")
        print(f"  Login: admin@aicloser.io / admin123")


if __name__ == "__main__":
    asyncio.run(seed())
