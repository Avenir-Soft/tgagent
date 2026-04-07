"""Test AI closer without Telegram — simulates a DM conversation."""

import asyncio
import sys

sys.path.insert(0, ".")

# Import all models to resolve relationships
from src.tenants.models import Tenant
from src.auth.models import User  # noqa
from src.telegram.models import *  # noqa
from src.catalog.models import *  # noqa
from src.conversations.models import Conversation
from src.leads.models import *  # noqa
from src.orders.models import *  # noqa
from src.handoffs.models import *  # noqa
from src.ai.models import *  # noqa
from src.core.audit import *  # noqa

from src.core.database import async_session_factory
from src.ai.orchestrator import process_dm_message
from sqlalchemy import select


async def main():
    async with async_session_factory() as db:
        # Get tenant
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one()
        print(f"Tenant: {tenant.name} ({tenant.id})\n")

        # Create a test conversation
        conv = Conversation(
            tenant_id=tenant.id,
            telegram_chat_id=999999,
            telegram_user_id=111111,
            source_type="dm",
            status="active",
            state="NEW_CHAT",
            ai_enabled=True,
        )
        db.add(conv)
        await db.flush()

        # Simulate a realistic sales conversation
        test_messages = [
            "Привет, есть айфон?",
            "Сколько стоит?",
            "А доставка по Ташкенту есть?",
            "Хочу купить, как оформить?",
            "Меня зовут Ойбек, номер +998977061605, Ташкент",
            "А laptop сколько стоит?",
            "Хочу скидку",
        ]

        for msg in test_messages:
            print(f"👤 Клиент: {msg}")
            result = await process_dm_message(
                tenant_id=tenant.id,
                conversation=conv,
                user_text=msg,
                db=db,
            )
            response = result.get("text") if isinstance(result, dict) else result
            print(f"🤖 AI: {response}")
            print(f"   [state: {conv.state}]")
            print()

        await db.rollback()  # don't save test data


if __name__ == "__main__":
    asyncio.run(main())
