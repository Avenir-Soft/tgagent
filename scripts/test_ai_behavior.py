"""Full AI behavior test — 25 scenarios covering all demo cases."""

import asyncio
import sys
import re

sys.path.insert(0, ".")

from sqlalchemy import select, text as sql_text
from src.core.database import async_session_factory
from src.conversations.models import Conversation, Message
from src.ai.orchestrator import process_dm_message

from src.tenants.models import *  # noqa
from src.auth.models import *  # noqa
from src.telegram.models import *  # noqa
from src.catalog.models import *  # noqa
from src.leads.models import *  # noqa
from src.orders.models import *  # noqa
from src.handoffs.models import *  # noqa
from src.ai.models import *  # noqa

SLUG = "easy-tour"
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; B = "\033[1m"; X = "\033[0m"


async def get_conv(db, tid, cid, label):
    r = await db.execute(select(Conversation).where(Conversation.tenant_id == tid, Conversation.telegram_chat_id == cid))
    c = r.scalar_one_or_none()
    if c: return c
    c = Conversation(tenant_id=tid, telegram_chat_id=cid, telegram_user_id=cid,
                     telegram_first_name=f"Test ({label})", source_type="dm", state="idle", state_context={}, ai_enabled=True)
    db.add(c); await db.flush()
    return c


async def msg(db, conv, tid, text):
    m = Message(tenant_id=tid, conversation_id=conv.id, direction="inbound", sender_type="customer", raw_text=text, normalized_text=text)
    db.add(m); await db.flush()
    result = await process_dm_message(tid, conv.id, text, db)
    if result is None: return None
    resp = result.get("text", "") if isinstance(result, dict) else (result[0] if isinstance(result, tuple) else result)
    if resp:
        am = Message(tenant_id=tid, conversation_id=conv.id, direction="outbound", sender_type="ai", raw_text=resp, normalized_text=resp)
        db.add(am); await db.flush()
    return resp


def cyr(t): return bool(re.search(r"[а-яА-ЯёЁўқғҳ]{3,}", t))
def lat(t): return bool(re.search(r"[a-zA-Z]{3,}", t))


async def run():
    print(f"\n{B}{C}{'='*60}\n  Easy Tour AI — FULL Behavior Test (25 scenarios)\n{'='*60}{X}\n")

    async with async_session_factory() as db:
        r = await db.execute(sql_text("SELECT id FROM tenants WHERE slug = :s"), {"s": SLUG})
        row = r.first()
        if not row: print(f"{R}Tenant not found!{X}"); return
        tid = row[0]

        ok = fail = total = 0
        chats = []

        def check(name, resp, rules):
            nonlocal ok, fail, total
            total += 1
            fails = []
            for desc, fn in rules:
                try:
                    if not fn(resp or ""): fails.append(desc)
                except Exception as e: fails.append(f"{desc} ({e})")
            if fails:
                fail += 1
                for f in fails: print(f"  {R}FAIL: {f}{X}")
            else:
                ok += 1; print(f"  {G}PASS{X}")
            print()

        # ═══════════ GROUP 1: GREETINGS ═══════════
        print(f"{B}{C}--- 1. GREETINGS ---{X}\n")

        print(f"{B}1.1 Salom{X}")
        c = await get_conv(db, tid, 700001, "g1"); chats.append(700001)
        r = await msg(db, c, tid, "Salom"); print(f"  < {r}")
        check("salom", r, [("exists", lambda r: len(r)>3), ("no russian", lambda r: not cyr(r)), ("has tur/yordam", lambda r: any(w in r.lower() for w in ["tur","yordam","qanday"]))])
        await db.commit()

        print(f"{B}1.2 Привет{X}")
        c = await get_conv(db, tid, 700002, "g2"); chats.append(700002)
        r = await msg(db, c, tid, "Привет"); print(f"  < {r}")
        check("privet", r, [("exists", lambda r: len(r)>3), ("has cyrillic", lambda r: cyr(r)), ("no товар/магазин", lambda r: not any(w in r.lower() for w in ["товар","магазин","электроник"]))])
        await db.commit()

        print(f"{B}1.3 Hi{X}")
        c = await get_conv(db, tid, 700003, "g3"); chats.append(700003)
        r = await msg(db, c, tid, "Hi"); print(f"  < {r}")
        check("hi", r, [("exists", lambda r: len(r)>3), ("english response", lambda r: lat(r))])
        await db.commit()

        print(f"{B}1.4 Assalomu alaykum{X}")
        c = await get_conv(db, tid, 700004, "g4"); chats.append(700004)
        r = await msg(db, c, tid, "Assalomu alaykum"); print(f"  < {r}")
        check("assalomu", r, [("exists", lambda r: len(r)>3), ("no russian", lambda r: not cyr(r))])
        await db.commit()

        # ═══════════ GROUP 2: TOUR SEARCH ═══════════
        print(f"{B}{C}--- 2. TOUR SEARCH ---{X}\n")

        print(f"{B}2.1 Qanday turlar bor?{X}")
        c = await get_conv(db, tid, 700010, "s1"); chats.append(700010)
        r = await msg(db, c, tid, "Qanday turlar bor?"); print(f"  < {r[:200]}...")
        check("categories", r, [("exists", lambda r: len(r)>10), ("has categories", lambda r: any(w in r.lower() for w in ["adrenalin","kemping","yurish","4x4"]))])
        await db.commit()

        print(f"{B}2.2 Sharshara{X}")
        c = await get_conv(db, tid, 700011, "s2"); chats.append(700011)
        r = await msg(db, c, tid, "Sharshara turlari bormi?"); print(f"  < {r[:200]}...")
        check("sharshara", r, [("mentions Paltau", lambda r: "paltau" in r.lower()), ("shows price", lambda r: "199" in r or "so'm" in r.lower())])
        await db.commit()

        print(f"{B}2.3 Какие туры есть? (Russian){X}")
        c = await get_conv(db, tid, 700012, "s3"); chats.append(700012)
        r = await msg(db, c, tid, "Какие туры у вас есть?"); print(f"  < {r[:200]}...")
        check("ru-tours", r, [("has cyrillic", lambda r: cyr(r)), ("no товар/магазин", lambda r: not any(w in r.lower() for w in ["товар","магазин","электроник"])), ("bilingual categories", lambda r: any(w in r for w in ["Адреналин","Кемпинг","поход"]))])
        await db.commit()

        print(f"{B}2.4 Non-existent: Dubay{X}")
        c = await get_conv(db, tid, 700013, "s4"); chats.append(700013)
        r = await msg(db, c, tid, "Dubayga tur bormi?"); print(f"  < {r}")
        check("not-found", r, [("exists", lambda r: len(r)>5), ("no электроник/магазин", lambda r: not any(w in r.lower() for w in ["электроник","магазин","покупк"])), ("suggests alternatives", lambda r: any(w in r.lower() for w in ["mavjud","boshqa","tur","ko'rsat"]))])
        await db.commit()

        print(f"{B}2.5 Non-existent Russian: Египет{X}")
        c = await get_conv(db, tid, 700014, "s5"); chats.append(700014)
        r = await msg(db, c, tid, "Есть туры в Египет?"); print(f"  < {r}")
        check("egypt-ru", r, [("has cyrillic", lambda r: cyr(r)), ("no магазин/электроник", lambda r: not any(w in r.lower() for w in ["магазин","электроник","покупк","товар"])), ("mentions tour/other", lambda r: any(w in r.lower() for w in ["тур","друг","доступн","нет","отсутств"]))])
        await db.commit()

        # ═══════════ GROUP 3: TOUR DETAILS ═══════════
        print(f"{B}{C}--- 3. TOUR DETAILS ---{X}\n")

        print(f"{B}3.1 Paltau details{X}")
        c = await get_conv(db, tid, 700020, "d1"); chats.append(700020)
        r = await msg(db, c, tid, "Paltau sharshara haqida batafsil"); print(f"  < {r[:250]}...")
        check("paltau-detail", r, [("mentions Paltau", lambda r: "paltau" in r.lower()), ("shows dates", lambda r: any(w in r.lower() for w in ["aprel","sana","vaqt"]))])
        await db.commit()

        print(f"{B}3.2 Chimgan price{X}")
        c = await get_conv(db, tid, 700021, "d2"); chats.append(700021)
        r = await msg(db, c, tid, "Chimgan qancha turadi?"); print(f"  < {r[:200]}...")
        check("chimgan-price", r, [("shows price number", lambda r: bool(re.search(r"\d{3}", r))), ("mentions so'm", lambda r: "so'm" in r.lower() or "сум" in r.lower())])
        await db.commit()

        print(f"{B}3.3 Bungee Russian details{X}")
        c = await get_conv(db, tid, 700022, "d3"); chats.append(700022)
        r = await msg(db, c, tid, "Расскажи про банджи джампинг подробнее"); print(f"  < {r[:250]}...")
        check("bungee-ru", r, [("has cyrillic", lambda r: cyr(r)), ("no со'm (mixed script)", lambda r: "со'm" not in r)])
        await db.commit()

        # ═══════════ GROUP 4: BOOKING FLOW ═══════════
        print(f"{B}{C}--- 4. BOOKING FLOW ---{X}\n")

        print(f"{B}4.1 Full booking: search → date → info → confirm{X}")
        c = await get_conv(db, tid, 700030, "b1"); chats.append(700030)
        r1 = await msg(db, c, tid, "Paltau sharsharaga bormoqchiman"); await db.commit()
        print(f"  Step 1: {r1[:100]}...")
        r2 = await msg(db, c, tid, "19-aprelga"); await db.commit()
        print(f"  Step 2: {r2[:100]}...")
        r3 = await msg(db, c, tid, "2 kishi, Alisher, 901234567"); await db.commit()
        print(f"  Step 3: {r3[:150]}...")
        check("booking-flow", r3, [("exists", lambda r: len(r)>5), ("mentions booking/confirm/payment", lambda r: any(w in r.lower() for w in ["bron","to'lov","buyurtma","bk-","tasdiqlang","chek"]))])
        await db.commit()

        print(f"{B}4.2 Booking without delivery/address{X}")
        # Already tested above — check no delivery
        check("no-delivery", r3, [("no adres", lambda r: "adres" not in r.lower()), ("no yetkazib berish", lambda r: "yetkazib" not in r.lower()), ("no доставк", lambda r: "доставк" not in r.lower())])

        # ═══════════ GROUP 5: ORDER STATUS ═══════════
        print(f"{B}{C}--- 5. ORDER STATUS ---{X}\n")

        print(f"{B}5.1 Check order status{X}")
        r = await msg(db, c, tid, "Buyurtmam qani?"); print(f"  < {r[:200]}...")
        check("order-status", r, [("exists", lambda r: len(r)>5), ("mentions status/order", lambda r: any(w in r.lower() for w in ["buyurtma","bron","holat","status","bk-","kutilmoqda","to'lov"]))])
        await db.commit()

        # ═══════════ GROUP 6: EDGE CASES ═══════════
        print(f"{B}{C}--- 6. EDGE CASES ---{X}\n")

        print(f"{B}6.1 Off-topic: math{X}")
        c = await get_conv(db, tid, 700040, "e1"); chats.append(700040)
        r = await msg(db, c, tid, "2+2 nechta?"); print(f"  < {r}")
        check("math", r, [("redirects to tours", lambda r: any(w in r.lower() for w in ["tur","yordam","ko'rsat"]))])
        await db.commit()

        print(f"{B}6.2 Off-topic Russian: анекдот{X}")
        c = await get_conv(db, tid, 700041, "e2"); chats.append(700041)
        r = await msg(db, c, tid, "Расскажи анекдот"); print(f"  < {r}")
        check("joke-ru", r, [("no магазин/электроник", lambda r: not any(w in r.lower() for w in ["магазин","электроник","покупк","товар"])), ("mentions тур", lambda r: "тур" in r.lower())])
        await db.commit()

        print(f"{B}6.3 Discount{X}")
        c = await get_conv(db, tid, 700042, "e3"); chats.append(700042)
        await msg(db, c, tid, "Chimgan qancha?"); await db.commit()
        r = await msg(db, c, tid, "Qimmat ekan, chegirma bormi?"); print(f"  < {r[:200]}...")
        check("discount", r, [("not rejected as off-topic", lambda r: "faqat tur" not in r.lower()), ("addresses pricing", lambda r: any(w in r.lower() for w in ["narx","belgilangan","boshqa","arzon","byudjet"]))])
        await db.commit()

        print(f"{B}6.4 Handoff request{X}")
        c = await get_conv(db, tid, 700043, "e4"); chats.append(700043)
        r = await msg(db, c, tid, "Odam bilan gaplashmoqchiman"); print(f"  < {r}")
        check("handoff", r, [("mentions operator", lambda r: any(w in r.lower() for w in ["operator","kuting","chaqir","uzat"]))])
        await db.commit()

        print(f"{B}6.5 Profanity{X}")
        c = await get_conv(db, tid, 700044, "e5"); chats.append(700044)
        r = await msg(db, c, tid, "Siktir naxuy"); print(f"  < {r}")
        check("profanity", r, [("exists", lambda r: len(r)>3), ("handoff or calm response", lambda r: any(w in r.lower() for w in ["operator","kuting","yordam","hurmat"]))])
        await db.commit()

        print(f"{B}6.6 Seats check{X}")
        c = await get_conv(db, tid, 700045, "e6"); chats.append(700045)
        r = await msg(db, c, tid, "Tuzkon kempingga joy bormi?"); print(f"  < {r[:200]}...")
        check("seats", r, [("mentions seats/joy", lambda r: any(w in r.lower() for w in ["joy","мест","seat","mavjud"]))])
        await db.commit()

        print(f"{B}6.7 No photo text in response{X}")
        c = await get_conv(db, tid, 700046, "e7"); chats.append(700046)
        r = await msg(db, c, tid, "Bungee jumping haqida ayt"); print(f"  < {r[:200]}...")
        check("no-photo-text", r, [("no [Fotosuratlar]", lambda r: "[Fotosuratlar]" not in r and "[📸" not in r), ("no 'yuboriladi'", lambda r: "yuboriladi" not in r.lower() or "foto" not in r.lower())])
        await db.commit()

        print(f"{B}6.8 Language: user asks 'русча гапиринг'{X}")
        c = await get_conv(db, tid, 700047, "e8"); chats.append(700047)
        await msg(db, c, tid, "Salom"); await db.commit()
        r = await msg(db, c, tid, "ruscha gapiring"); print(f"  < {r}")
        check("switch-to-ru", r, [("has cyrillic (switched)", lambda r: cyr(r))])
        await db.commit()

        # ═══════════ RESULTS ═══════════
        print(f"\n{B}{C}{'='*60}")
        print(f"  RESULTS: {ok}/{total} passed, {fail} failed")
        print(f"{'='*60}{X}")
        if fail == 0:
            print(f"\n{G}{B}ALL TESTS PASSED!{X}")
        else:
            print(f"\n{Y}{B}{fail} tests need fixes.{X}")

        # Cleanup
        print(f"\n{C}Cleaning up test data...{X}")
        for cid in chats:
            r = await db.execute(select(Conversation).where(Conversation.tenant_id == tid, Conversation.telegram_chat_id == cid))
            cv = r.scalar_one_or_none()
            if cv:
                await db.execute(sql_text("DELETE FROM messages WHERE conversation_id = :c"), {"c": str(cv.id)})
                await db.execute(sql_text("DELETE FROM handoffs WHERE conversation_id = :c"), {"c": str(cv.id)})
                await db.execute(sql_text("DELETE FROM conversations WHERE id = :c"), {"c": str(cv.id)})
        await db.commit()
        print(f"{G}Clean!{X}\n")


if __name__ == "__main__":
    asyncio.run(run())
