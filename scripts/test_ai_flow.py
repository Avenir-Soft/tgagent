"""Full AI agent test — simulates conversation flow via process_dm_message.

Tests:
1. Greeting in Uzbek Latin → should respond in Latin
2. Browse products → list categories
3. Select product → show variants
4. Add to cart → checkout → create order
5. Modify order → add item
6. Cancel order
7. Alias/stock checks
8. Language consistency (Latin Uzbek throughout)
"""

import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm.attributes import flag_modified

# Add project root to path
sys.path.insert(0, ".")

# Import ALL models first so SQLAlchemy resolves foreign keys
from src.core.database import async_session_factory
import src.tenants.models  # noqa: F401 — Tenant
import src.auth.models  # noqa: F401 — User
import src.catalog.models  # noqa: F401 — Product, Variant, etc.
import src.conversations.models  # noqa: F401
import src.orders.models  # noqa: F401
import src.leads.models  # noqa: F401
import src.telegram.models  # noqa: F401
import src.handoffs.models  # noqa: F401
import src.ai.models  # noqa: F401
from src.ai.orchestrator import process_dm_message, _detect_language, _check_greeting
from src.conversations.models import Conversation


TENANT_ID = UUID("a7b1be91-b75f-4088-848a-22705b44b1b2")

# Use an existing conversation for testing
TEST_CONVERSATION_ID = None  # Will be set dynamically


async def reset_conversation(db, conv_id: UUID):
    """Reset conversation to clean state for testing."""
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if conv:
        conv.state = "idle"
        conv.state_context = {}
        conv.ai_enabled = True
        flag_modified(conv, "state_context")
        await db.commit()
        print(f"  [RESET] Conversation reset to idle, context cleared")


async def send_message(db, conv_id: UUID, text: str) -> str:
    """Send a message and get AI response."""
    # Save inbound message
    from src.conversations.models import Message
    from datetime import datetime, timezone

    msg = Message(
        tenant_id=TENANT_ID,
        conversation_id=conv_id,
        direction="inbound",
        sender_type="customer",
        raw_text=text,
        normalized_text=text.strip().lower(),
    )
    db.add(msg)
    await db.flush()

    # Process through AI
    response = await process_dm_message(
        tenant_id=TENANT_ID,
        conversation_id=conv_id,
        user_message=text,
        db=db,
    )

    # Handle dict return (text + image_urls) or plain string
    if isinstance(response, dict):
        response_text = response.get("text")
        image_urls = response.get("image_urls", [])
    else:
        response_text = response
        image_urls = []

    if response_text:
        # Save outbound message
        out_msg = Message(
            tenant_id=TENANT_ID,
            conversation_id=conv_id,
            direction="outbound",
            sender_type="ai",
            raw_text=response_text,
            ai_generated=True,
        )
        db.add(out_msg)
        await db.flush()

    if image_urls:
        print(f"  📷 Images: {image_urls}")
    return response_text or "(no response)"


def check_language(response: str, expected_script: str) -> str:
    """Check if response is in expected script."""
    cyrillic = sum(1 for c in response if "\u0400" <= c <= "\u04FF")
    latin = sum(1 for c in response if "a" <= c.lower() <= "z")
    total = cyrillic + latin

    if total == 0:
        return "UNKNOWN"

    if expected_script == "latin":
        if cyrillic > total * 0.3:
            return f"FAIL (cyrillic: {cyrillic}, latin: {latin} — too much Cyrillic!)"
        return "OK"
    elif expected_script == "cyrillic":
        if latin > total * 0.3:
            return f"FAIL (cyrillic: {cyrillic}, latin: {latin} — too much Latin!)"
        return "OK"
    return "OK"


async def run_tests():
    print("=" * 70)
    print("AI AGENT FULL TEST SUITE")
    print("=" * 70)

    # --- Test 1: Language Detection ---
    print("\n📋 TEST 1: Language Detection")
    lang_tests = [
        ("salom", "ru", "uz_latin"),
        ("Assalomu alaykum", "ru", "uz_latin"),
        ("hi", "ru", "en"),
        ("i wanna order", "ru", "en"),
        ("привет", "ru", "ru"),
        ("салом", "ru", "uz_cyrillic"),
        ("qalesan", "ru", "uz_latin"),
        ("yaxshimisiz oka", "ru", "uz_latin"),
        ("oka ayfon zakaz qimoqchidim", "ru", "uz_latin"),
        ("15 pro bormi", "uz_latin", "uz_latin"),
        ("977061605", "uz_latin", "uz_latin"),  # phone number should keep current
        ("da", "uz_latin", "uz_latin"),
    ]
    passed = 0
    for text, cur, expected in lang_tests:
        result = _detect_language(text, cur)
        ok = result == expected
        passed += ok
        status = "✅" if ok else "❌"
        if not ok:
            print(f"  {status} '{text}' (cur={cur}): got={result}, expected={expected}")
    print(f"  Language detection: {passed}/{len(lang_tests)} passed")

    # --- Test 2: Greeting Handler ---
    print("\n📋 TEST 2: Greeting Handler")
    greet_tests = [
        ("salom", "uz_latin", True, "latin"),
        ("Assalomu alaykum", "uz_latin", True, "latin"),
        ("hi", "en", True, None),
        ("привет", "ru", True, None),
        ("салом", "uz_cyrillic", True, "cyrillic"),
        ("qalesan", "uz_latin", True, "latin"),
        ("oka ayfon zakaz qimoqchidim", "uz_latin", False, None),
        ("покажи телефоны", "ru", False, None),
    ]
    passed = 0
    for text, lang, should_match, check_script in greet_tests:
        result = _check_greeting(text, lang)
        matched = result is not None
        ok = matched == should_match
        if check_script and result:
            script_check = check_language(result, check_script)
            if "FAIL" in script_check:
                ok = False
                print(f"  ❌ '{text}' → {result} — SCRIPT {script_check}")
        passed += ok
        if not ok and not (check_script and result):
            print(f"  ❌ '{text}': matched={matched}, expected={should_match}, response={result}")
    print(f"  Greeting handler: {passed}/{len(greet_tests)} passed")

    # --- Test 3-7: Full Conversation Flow ---
    print("\n📋 TEST 3-7: Full Conversation Flow (Uzbek Latin)")
    print("-" * 50)

    async with async_session_factory() as db:
        # Find test conversation
        result = await db.execute(
            select(Conversation).where(
                Conversation.tenant_id == TENANT_ID,
            ).order_by(Conversation.created_at.desc()).limit(1)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            print("  ❌ No conversation found for testing!")
            return

        conv_id = conv.id
        print(f"  Using conversation: {conv.telegram_first_name} ({conv_id})")

        # Reset conversation
        await reset_conversation(db, conv_id)

        # --- Step 1: Greeting ---
        print("\n  🔸 Step 1: Greeting (Uzbek Latin)")
        resp = await send_message(db, conv_id, "Assalomu alaykum")
        print(f"  USER: Assalomu alaykum")
        print(f"  AI:   {resp}")
        script = check_language(resp, "latin")
        print(f"  Script check: {script}")
        await db.commit()

        # --- Step 2: Ask for products ---
        print("\n  🔸 Step 2: Browse products")
        resp = await send_message(db, conv_id, "telefon bormi")
        print(f"  USER: telefon bormi")
        print(f"  AI:   {resp}")
        script = check_language(resp, "latin")
        print(f"  Script check: {script}")
        await db.commit()

        # --- Step 3: Select a product ---
        print("\n  🔸 Step 3: Select product variant")
        resp = await send_message(db, conv_id, "iPhone 15 Pro variantlarini ko'rsat")
        print(f"  USER: iPhone 15 Pro variantlarini ko'rsat")
        print(f"  AI:   {resp}")
        await db.commit()

        # --- Step 4: Add to cart ---
        print("\n  🔸 Step 4: Add to cart (black variant)")
        resp = await send_message(db, conv_id, "qora rangini qo'sh")
        print(f"  USER: qora rangini qo'sh")
        print(f"  AI:   {resp}")
        await db.commit()

        # Check state_context
        result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
        conv = result.scalar_one_or_none()
        ctx = conv.state_context or {}
        cart = ctx.get("cart", [])
        print(f"  Cart: {json.dumps(cart, ensure_ascii=False, indent=2) if cart else 'EMPTY'}")

        # --- Step 5: Checkout ---
        print("\n  🔸 Step 5: Checkout")
        resp = await send_message(db, conv_id, "hammasi shu, zakaz qilaman")
        print(f"  USER: hammasi shu, zakaz qilaman")
        print(f"  AI:   {resp}")
        await db.commit()

        # --- Step 6: Provide delivery info ---
        print("\n  🔸 Step 6: Provide delivery info")
        resp = await send_message(db, conv_id, "Oybek, 998901234567, Toshkent, Mirzo Ulugbek 39")
        print(f"  USER: Oybek, 998901234567, Toshkent, Mirzo Ulugbek 39")
        print(f"  AI:   {resp}")
        await db.commit()

        # Check if order was created
        result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
        conv = result.scalar_one_or_none()
        ctx = conv.state_context or {}
        orders = ctx.get("orders", [])
        print(f"  Orders in context: {json.dumps(orders, ensure_ascii=False, indent=2) if orders else 'NONE'}")

        if orders:
            order_number = orders[-1].get("order_number", "")
            print(f"  Order number: {order_number}")

            # --- Step 7: Modify order (add item) ---
            print(f"\n  🔸 Step 7: Add item to order {order_number}")
            resp = await send_message(db, conv_id, f"oka {order_number} ga AirPods qo'shib ber")
            print(f"  USER: oka {order_number} ga AirPods qo'shib ber")
            print(f"  AI:   {resp}")
            await db.commit()

            # --- Step 8: Cancel order ---
            print(f"\n  🔸 Step 8: Cancel order {order_number}")
            resp = await send_message(db, conv_id, f"{order_number} ni bekor qil")
            print(f"  USER: {order_number} ni bekor qil")
            print(f"  AI:   {resp}")
            await db.commit()
        else:
            print("  ⚠️  No order created — skipping modify/cancel tests")

        # --- Step 9: Test phone number NOT matching as order ---
        print("\n  🔸 Step 9: Phone number should NOT match as order")
        await reset_conversation(db, conv_id)
        await db.commit()

        # Set state to checkout to verify skip
        result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
        conv = result.scalar_one_or_none()
        conv.state = "cart"
        conv.state_context = {"cart": [{"variant_id": "test", "title": "Test", "price": 1000, "qty": 1}], "language": "uz_latin"}
        flag_modified(conv, "state_context")
        await db.commit()

        resp = await send_message(db, conv_id, "Oybek 977061605 Toshkent")
        print(f"  USER: Oybek 977061605 Toshkent")
        print(f"  AI:   {resp}")
        has_order_not_found = "не найден" in (resp or "").lower() or "topilmadi" in (resp or "").lower()
        print(f"  Phone matched as order: {'❌ YES (BUG!)' if has_order_not_found else '✅ NO (correct)'}")
        await db.commit()

        # --- Step 10: Test alias search ---
        print("\n  🔸 Step 10: Test alias search (Uzbek terms)")
        await reset_conversation(db, conv_id)
        await db.commit()

        resp = await send_message(db, conv_id, "salom")
        await db.commit()

        resp = await send_message(db, conv_id, "noutbuk bormi")
        print(f"  USER: noutbuk bormi")
        print(f"  AI:   {resp}")
        await db.commit()

    print("\n" + "=" * 70)
    print("TEST COMPLETE — review results above")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())
