"""Full scenario test — ~70 messages simulating a real customer journey.

One conversation: greeting → browsing → questions → booking → status check → new tour interest.
Tests language detection, multi-tour browsing, booking flow, order status, edge cases.
Operator notification sent to @oybeff.
"""

import asyncio
import sys
import re
import time

sys.path.insert(0, ".")

from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import selectinload
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
CHAT_ID = 888001  # unique test chat
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; B = "\033[1m"; X = "\033[0m"; D = "\033[2m"

msg_count = 0
pass_count = 0
fail_count = 0
fails_list = []


async def send(db, conv, tid, text, label=""):
    """Send a message and get AI response."""
    global msg_count
    msg_count += 1
    m = Message(tenant_id=tid, conversation_id=conv.id, direction="inbound",
                sender_type="customer", raw_text=text, normalized_text=text)
    db.add(m)
    await db.flush()
    t0 = time.time()
    result = await process_dm_message(tid, conv.id, text, db)
    elapsed = time.time() - t0
    if result is None:
        return None
    resp = result.get("text", "") if isinstance(result, dict) else (result[0] if isinstance(result, tuple) else result)
    if resp:
        am = Message(tenant_id=tid, conversation_id=conv.id, direction="outbound",
                     sender_type="ai", raw_text=resp, normalized_text=resp)
        db.add(am)
        await db.flush()
    prefix = f"  {D}#{msg_count}{X}"
    tag = f" {Y}[{label}]{X}" if label else ""
    print(f"{prefix}{tag} {B}>{X} {text}")
    short = (resp or "—")[:160].replace("\n", " ↵ ")
    print(f"{prefix}  {C}<{X} {short}{'...' if resp and len(resp) > 160 else ''} {D}({elapsed:.1f}s){X}")
    return resp


def check(name, resp, rules):
    global pass_count, fail_count
    fails = []
    for desc, fn in rules:
        try:
            if not fn(resp or ""):
                fails.append(desc)
        except Exception as e:
            fails.append(f"{desc} ({e})")
    if fails:
        fail_count += 1
        for f in fails:
            print(f"  {R}  ✗ {f}{X}")
            fails_list.append(f"{name}: {f}")
    else:
        pass_count += 1
        print(f"  {G}  ✓ OK{X}")


def cyr(t): return bool(re.search(r"[а-яА-ЯёЁўқғҳ]{3,}", t))
def lat(t): return bool(re.search(r"[a-zA-Z]{3,}", t))


async def run():
    print(f"\n{B}{C}{'='*70}")
    print(f"  Easy Tour AI — FULL SCENARIO (~70 messages)")
    print(f"{'='*70}{X}\n")

    async with async_session_factory() as db:
        r = await db.execute(sql_text("SELECT id FROM tenants WHERE slug = :s"), {"s": SLUG})
        row = r.first()
        if not row:
            print(f"{R}Tenant not found!{X}")
            return
        tid = row[0]

        # Create conversation
        c = Conversation(
            tenant_id=tid, telegram_chat_id=CHAT_ID, telegram_user_id=CHAT_ID,
            telegram_first_name="Javohir (test)", source_type="dm",
            state="idle", state_context={}, ai_enabled=True,
        )
        db.add(c)
        await db.flush()
        await db.commit()

        # ═══════════════════════════════════════════════════
        # PHASE 1: GREETING & DISCOVERY (msgs 1-10)
        # ═══════════════════════════════════════════════════
        print(f"\n{B}{C}--- PHASE 1: GREETING & DISCOVERY ---{X}\n")

        r = await send(db, c, tid, "Salom!", "greeting-uz")
        check("greeting", r, [("response exists", lambda r: len(r) > 3), ("no russian", lambda r: not cyr(r))])
        await db.commit()

        r = await send(db, c, tid, "Qanday turlar bor?", "categories")
        check("categories", r, [("shows categories", lambda r: any(w in r.lower() for w in ["adrenalin", "kemping", "yurish"]))])
        await db.commit()

        r = await send(db, c, tid, "Yengil yurish turlari", "yengil-filter")
        check("yengil", r, [("mentions Paltau/Chukuraksu/Ispay", lambda r: sum(1 for w in ["paltau", "chukuraksu", "ispay"] if w in r.lower()) >= 2)])
        await db.commit()

        r = await send(db, c, tid, "Eng arzonlari qaysi?", "cheapest")
        check("cheapest", r, [("mentions price", lambda r: "199" in r)])
        await db.commit()

        r = await send(db, c, tid, "Adrenalinli turlar ham bor?", "adrenalin")
        check("adrenalin", r, [("mentions bungee/zipline", lambda r: any(w in r.lower() for w in ["bungee", "zipline"]))])
        await db.commit()

        r = await send(db, c, tid, "Bungee jumping haqida batafsil", "bungee-detail")
        check("bungee-detail", r, [("shows price", lambda r: "500" in r), ("no fake photo text", lambda r: "[Fotosuratlar]" not in r)])
        await db.commit()

        r = await send(db, c, tid, "Qachon bo'ladi?", "bungee-date")
        check("bungee-date", r, [("mentions date", lambda r: "aprel" in r.lower() or "20" in r)])
        await db.commit()

        r = await send(db, c, tid, "Nechta joy qolgan?", "bungee-seats")
        check("bungee-seats", r, [("mentions seats/joy", lambda r: any(w in r.lower() for w in ["joy", "seat", "mavjud", "qol"]))])
        await db.commit()

        r = await send(db, c, tid, "Yo'q, oldin sharsharalarni ko'ray", "switch-back")
        check("switch-back", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "Paltau sharshara haqida ayt", "paltau-info")
        check("paltau-info", r, [("mentions Paltau", lambda r: "paltau" in r.lower()), ("shows price", lambda r: "199" in r)])
        await db.commit()

        # ═══════════════════════════════════════════════════
        # PHASE 2: DETAILED QUESTIONS (msgs 11-25)
        # ═══════════════════════════════════════════════════
        print(f"\n{B}{C}--- PHASE 2: DETAILED QUESTIONS ---{X}\n")

        r = await send(db, c, tid, "Qaysi sanalar bor?", "paltau-dates")
        check("paltau-dates", r, [("shows dates", lambda r: "aprel" in r.lower() or "19" in r or "26" in r)])
        await db.commit()

        r = await send(db, c, tid, "Yig'ilish joyi qayerda?", "meeting-point")
        check("meeting-point", r, [("responds", lambda r: len(r) > 10)])
        await db.commit()

        r = await send(db, c, tid, "Nimalar kiritilgan narxga?", "whats-included")
        check("included", r, [("responds with info", lambda r: len(r) > 20)])
        await db.commit()

        r = await send(db, c, tid, "Nima olib kelish kerak?", "what-to-bring")
        check("what-to-bring", r, [("responds", lambda r: len(r) > 10)])
        await db.commit()

        r = await send(db, c, tid, "Bolalar uchun ham bormi? 7 yoshli bola bor", "kids")
        check("kids", r, [("responds", lambda r: len(r) > 10)])
        await db.commit()

        r = await send(db, c, tid, "Qimmat ekan. Arzonroq tur bormi?", "cheaper-ask")
        check("cheaper", r, [("doesn't reject", lambda r: "faqat tur" not in r.lower()), ("offers alternatives", lambda r: len(r) > 20)])
        await db.commit()

        r = await send(db, c, tid, "Kemping turi bormi?", "kemping-ask")
        check("kemping", r, [("mentions Tuzkon", lambda r: "tuzkon" in r.lower())])
        await db.commit()

        r = await send(db, c, tid, "Tuzkon kemping qancha?", "tuzkon-price")
        check("tuzkon-price", r, [("shows 699", lambda r: "699" in r)])
        await db.commit()

        r = await send(db, c, tid, "Xalqaro turlar bormi?", "international")
        check("international", r, [("mentions Qirg'iziston", lambda r: "irg" in r.lower())])
        await db.commit()

        r = await send(db, c, tid, "Qirg'iziston qancha turadi?", "kg-price")
        check("kg-price", r, [("shows price", lambda r: "2" in r and "280" in r or "2280" in r.replace(" ", ""))])
        await db.commit()

        r = await send(db, c, tid, "Yaxshi, Paltauga qaytay", "back-to-paltau")
        check("back-to-paltau", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "19-aprel qachon chiqamiz?", "19apr-time")
        check("19apr-time", r, [("mentions time", lambda r: any(w in r.lower() for w in ["08:00", "8:00", "erta", "vaqt"]))])
        await db.commit()

        r = await send(db, c, tid, "Transport bormi yoki o'zimiz kelamizmi?", "transport")
        check("transport", r, [("responds", lambda r: len(r) > 10)])
        await db.commit()

        r = await send(db, c, tid, "Ovqat kiritilganmi?", "food")
        check("food", r, [("responds", lambda r: len(r) > 10)])
        await db.commit()

        r = await send(db, c, tid, "Chegirma bormi 3 kishiga?", "discount-3")
        check("discount-3", r, [("addresses pricing", lambda r: len(r) > 10)])
        await db.commit()

        # ═══════════════════════════════════════════════════
        # PHASE 3: BOOKING (msgs 26-35)
        # ═══════════════════════════════════════════════════
        print(f"\n{B}{C}--- PHASE 3: BOOKING ---{X}\n")

        r = await send(db, c, tid, "Paltau sharsharaga 19-aprelga 3 kishi bron qilmoqchiman", "start-booking")
        check("start-booking", r, [("asks name/phone or confirms", lambda r: any(w in r.lower() for w in ["ism", "telefon", "ma'lumot", "paltau", "to'g'ri"]))])
        await db.commit()

        r = await send(db, c, tid, "Javohir, 901234567", "give-info")
        check("give-info", r, [("confirms/creates", lambda r: any(w in r.lower() for w in ["bron", "to'g'ri", "tasdiqlang", "bk-", "to'lov"]))])
        await db.commit()

        r = await send(db, c, tid, "Ha, to'g'ri", "confirm")
        check("confirm", r, [("booking created or confirmed", lambda r: any(w in r.lower() for w in ["bk-", "bron", "to'lov", "chek", "yaratildi"]))])
        await db.commit()

        # Save the booking number
        booking_num = None
        bk_match = re.search(r'BK-[A-Fa-f0-9]+', r or "")
        if bk_match:
            booking_num = bk_match.group()
            print(f"\n  {G}Booking created: {booking_num}{X}\n")
        else:
            print(f"\n  {Y}No booking number found in response, checking DB...{X}")
            bk_result = await db.execute(
                sql_text("SELECT order_number FROM orders WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 1"),
                {"t": str(tid)}
            )
            bk_row = bk_result.first()
            if bk_row:
                booking_num = bk_row[0]
                print(f"  {G}Found in DB: {booking_num}{X}\n")

        r = await send(db, c, tid, "To'lov qanday qilaman?", "payment-how")
        check("payment-how", r, [("mentions payment method", lambda r: any(w in r.lower() for w in ["payme", "click", "naqd", "chek", "to'lov"]))])
        await db.commit()

        r = await send(db, c, tid, "Payme orqali to'layman", "payment-payme")
        check("payment-payme", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        # Simulate sending payment receipt photo
        r = await send(db, c, tid, "[Клиент отправил фото]", "payment-receipt")
        check("payment-receipt", r, [("responds about receipt/handoff", lambda r: any(w in r.lower() for w in ["chek", "operator", "kuting", "qabul", "tasdiq"]))])
        await db.commit()

        # ═══════════════════════════════════════════════════
        # PHASE 4: POST-BOOKING QUESTIONS (msgs 32-45)
        # Re-enable AI for more questions
        # ═══════════════════════════════════════════════════
        print(f"\n{B}{C}--- PHASE 4: POST-BOOKING QUESTIONS ---{X}\n")

        # Re-enable AI (simulating operator confirmed and AI got re-enabled)
        await db.execute(
            sql_text("UPDATE conversations SET ai_enabled = true, status = 'active' WHERE id = :cid"),
            {"cid": str(c.id)}
        )
        await db.commit()
        # Refresh conversation object
        await db.refresh(c)

        r = await send(db, c, tid, "Buyurtmam holati qanday?", "order-status")
        check("order-status", r, [("mentions booking/status", lambda r: any(w in r.lower() for w in ["buyurtma", "bron", "holat", "status", "to'lov", "bk-"]))])
        await db.commit()

        r = await send(db, c, tid, "Nechta kishi boradi shu turga?", "how-many-people")
        check("how-many-people", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "Ob-havo qanday bo'ladi 19-aprelda?", "weather")
        check("weather", r, [("redirects to tours", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "Suv ichish joyiga olib borish kerakmi?", "water")
        check("water", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "Yana bitta do'stim ham bormoqchi, qo'shsa bo'ladimi?", "add-friend")
        check("add-friend", r, [("responds", lambda r: len(r) > 10)])
        await db.commit()

        # ═══════════════════════════════════════════════════
        # PHASE 5: RUSSIAN LANGUAGE (msgs 38-48)
        # ═══════════════════════════════════════════════════
        print(f"\n{B}{C}--- PHASE 5: RUSSIAN LANGUAGE ---{X}\n")

        r = await send(db, c, tid, "ruscha gapiring", "switch-ru")
        check("switch-ru", r, [("responds in russian", lambda r: cyr(r))])
        await db.commit()

        r = await send(db, c, tid, "Какие ещё туры есть кроме Палтау?", "ru-other-tours")
        check("ru-other", r, [("has cyrillic", lambda r: cyr(r)), ("mentions tours", lambda r: any(w in r.lower() for w in ["тур", "поход", "адреналин"]))])
        await db.commit()

        r = await send(db, c, tid, "Расскажи про зиплайн", "ru-zipline")
        check("ru-zipline", r, [("in russian", lambda r: cyr(r)), ("mentions zipline/price", lambda r: "550" in r or "зиплайн" in r.lower() or "zipline" in r.lower())])
        await db.commit()

        r = await send(db, c, tid, "А кемпинг дороже?", "ru-kemping-compare")
        check("ru-compare", r, [("in russian", lambda r: cyr(r))])
        await db.commit()

        r = await send(db, c, tid, "Какой самый дорогой тур?", "ru-most-expensive")
        check("ru-expensive", r, [("in russian", lambda r: cyr(r)), ("mentions expensive tour", lambda r: any(w in r.lower() for w in ["кирг", "хива", "chimgan", "чимган", "2 280", "2280", "2 345", "999"]))])
        await db.commit()

        r = await send(db, c, tid, "А на Кыргызстан виза нужна?", "ru-visa")
        check("ru-visa", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "Расскажи про тур в Хиву подробнее", "ru-xiva")
        check("ru-xiva", r, [("in russian", lambda r: cyr(r)), ("mentions xiva/price or searches", lambda r: "999" in r or "хива" in r.lower() or "xiva" in r.lower() or len(r) > 20)])
        await db.commit()

        r = await send(db, c, tid, "Мне нравится, но я уже забронировал Палтау. Когда следующий Хива?", "ru-next-xiva")
        check("ru-next-xiva", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "Можно ли отменить Палтау и забронировать Хиву?", "ru-cancel-rebook")
        check("ru-cancel-rebook", r, [("addresses cancellation", lambda r: len(r) > 10)])
        await db.commit()

        r = await send(db, c, tid, "Не, не надо, оставим Палтау", "ru-keep")
        check("ru-keep", r, [("responds", lambda r: len(r) > 3)])
        await db.commit()

        r = await send(db, c, tid, "Сколько стоит Mewa Party?", "ru-mewa")
        check("ru-mewa", r, [("mentions price", lambda r: "400" in r)])
        await db.commit()

        # ═══════════════════════════════════════════════════
        # PHASE 6: ENGLISH (msgs 49-53)
        # ═══════════════════════════════════════════════════
        print(f"\n{B}{C}--- PHASE 6: ENGLISH ---{X}\n")

        r = await send(db, c, tid, "Can you speak English?", "switch-en")
        check("switch-en", r, [("responds in english", lambda r: lat(r) and not cyr(r))])
        await db.commit()

        r = await send(db, c, tid, "What tours do you have?", "en-tours")
        check("en-tours", r, [("in english", lambda r: lat(r)), ("mentions categories/tours", lambda r: any(w in r.lower() for w in ["tour", "hiking", "adventure", "camping"]))])
        await db.commit()

        r = await send(db, c, tid, "How much is the Tuzkon camping?", "en-tuzkon")
        check("en-tuzkon", r, [("in english", lambda r: lat(r)), ("mentions price", lambda r: "699" in r)])
        await db.commit()

        r = await send(db, c, tid, "What's the cheapest tour you have?", "en-cheapest")
        check("en-cheapest", r, [("in english", lambda r: lat(r)), ("responds about tours/price", lambda r: "199" in r or "tour" in r.lower() or "cheap" in r.lower() or len(r) > 20)])
        await db.commit()

        r = await send(db, c, tid, "Thanks, I'll think about it", "en-thanks")
        check("en-thanks", r, [("responds politely", lambda r: len(r) > 3)])
        await db.commit()

        # ═══════════════════════════════════════════════════
        # PHASE 7: EDGE CASES & STRESS (msgs 54-65)
        # ═══════════════════════════════════════════════════
        print(f"\n{B}{C}--- PHASE 7: EDGE CASES ---{X}\n")

        r = await send(db, c, tid, "o'zbekchaga qayt", "switch-back-uz")
        check("back-to-uz", r, [("no russian", lambda r: not cyr(r) or len(r) < 10)])
        await db.commit()

        r = await send(db, c, tid, "2+2 nechta?", "math")
        check("math", r, [("redirects", lambda r: any(w in r.lower() for w in ["tur", "yordam"]))])
        await db.commit()

        r = await send(db, c, tid, "Dubayga turlar bormi?", "dubai")
        check("dubai", r, [("says not available", lambda r: any(w in r.lower() for w in ["yo'q", "mavjud emas", "hozirda"]))])
        await db.commit()

        r = await send(db, c, tid, "Turkiyaga-chi?", "turkey")
        check("turkey", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "Hafta oxiriga tur bormi?", "weekend")
        check("weekend", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "Eng ko'p joy qolgan tur qaysi?", "most-seats")
        check("most-seats", r, [("responds", lambda r: len(r) > 10)])
        await db.commit()

        r = await send(db, c, tid, "Oilam bilan bormoqchiman, 5 kishi. Tavsiya bering", "family-5")
        check("family-5", r, [("recommends", lambda r: len(r) > 20)])
        await db.commit()

        r = await send(db, c, tid, "Ishlaysizlarmi hozir?", "working-hours")
        check("working", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "Rahmat, juda yaxshi xizmat!", "compliment")
        check("compliment", r, [("responds warmly", lambda r: len(r) > 3)])
        await db.commit()

        r = await send(db, c, tid, "Mewa Party haqida gapirib bering", "mewa-party")
        check("mewa-party", r, [("mentions Mewa", lambda r: "mewa" in r.lower()), ("shows price", lambda r: "400" in r)])
        await db.commit()

        r = await send(db, c, tid, "130 ta joy bormi haqiqatdan?", "mewa-seats")
        check("mewa-seats", r, [("confirms seats", lambda r: "130" in r or any(w in r.lower() for w in ["joy", "mavjud"]))])
        await db.commit()

        r = await send(db, c, tid, "Oqtosh tog' yurish haqida aytib bering", "oqtosh")
        check("oqtosh", r, [("mentions Oqtosh", lambda r: "oqtosh" in r.lower()), ("shows price", lambda r: "350" in r)])
        await db.commit()

        # ═══════════════════════════════════════════════════
        # PHASE 8: FINAL ROUND (msgs 66-70)
        # ═══════════════════════════════════════════════════
        print(f"\n{B}{C}--- PHASE 8: FINAL ---{X}\n")

        r = await send(db, c, tid, "Hammasi juda zo'r. Keyingi safar Tuzkon kempingga ham boray", "next-time")
        check("next-time", r, [("responds", lambda r: len(r) > 5)])
        await db.commit()

        r = await send(db, c, tid, "19-aprelda Paltauda ko'rishamiz!", "see-you")
        check("see-you", r, [("responds warmly", lambda r: len(r) > 3)])
        await db.commit()

        r = await send(db, c, tid, "Xayr!", "bye")
        check("bye", r, [("responds", lambda r: len(r) > 2)])
        await db.commit()

        # ═══════════════════════════════════════════════════
        # RESULTS
        # ═══════════════════════════════════════════════════
        total = pass_count + fail_count
        print(f"\n{B}{C}{'='*70}")
        print(f"  RESULTS: {pass_count}/{total} passed, {fail_count} failed")
        print(f"  Total messages sent: {msg_count}")
        print(f"{'='*70}{X}")

        if fails_list:
            print(f"\n{R}Failed checks:{X}")
            for f in fails_list:
                print(f"  {R}✗ {f}{X}")

        if fail_count == 0:
            print(f"\n{G}{B}ALL CHECKS PASSED! 🎉{X}")
        else:
            print(f"\n{Y}{B}{fail_count} checks need attention.{X}")

        # Check operator notification was configured
        ai_result = await db.execute(
            sql_text("SELECT operator_telegram_username FROM ai_settings WHERE tenant_id = :t"),
            {"t": str(tid)}
        )
        ai_row = ai_result.first()
        if ai_row and ai_row[0]:
            print(f"\n{G}Operator notifications → @{ai_row[0]}{X}")
        else:
            print(f"\n{Y}⚠ No operator_telegram_username set!{X}")

        # Count orders created
        orders_result = await db.execute(
            sql_text("""
                SELECT o.order_number, o.status, o.total_amount, o.customer_name
                FROM orders o
                JOIN leads l ON l.id = o.lead_id
                JOIN conversations cv ON cv.id = l.conversation_id
                WHERE cv.telegram_chat_id = :cid AND o.tenant_id = :t
            """),
            {"cid": CHAT_ID, "t": str(tid)}
        )
        orders = orders_result.fetchall()
        if orders:
            print(f"\n{G}Orders created:{X}")
            for o in orders:
                print(f"  {o[0]} | {o[1]} | {o[2]} UZS | {o[3]}")

        # Count handoffs created
        handoffs_result = await db.execute(
            sql_text("SELECT reason, priority FROM handoffs WHERE conversation_id = :cid"),
            {"cid": str(c.id)}
        )
        handoffs = handoffs_result.fetchall()
        if handoffs:
            print(f"\n{G}Handoffs created:{X}")
            for h in handoffs:
                print(f"  [{h[1]}] {h[0][:80]}")

        # Cleanup — skip if --keep flag
        import sys as _sys
        if "--keep" in _sys.argv:
            print(f"\n{G}Data kept! Open conversation at:{X}")
            print(f"  {C}http://localhost:3000/conversations/{c.id}{X}\n")
        else:
            print(f"\n{C}Cleaning up test data...{X}")
            await db.execute(sql_text("DELETE FROM handoffs WHERE conversation_id = :c"), {"c": str(c.id)})
            await db.execute(sql_text("""
                DELETE FROM order_items WHERE order_id IN (
                    SELECT o.id FROM orders o JOIN leads l ON l.id = o.lead_id
                    JOIN conversations cv ON cv.id = l.conversation_id
                    WHERE cv.telegram_chat_id = :cid AND o.tenant_id = :t
                )
            """), {"cid": CHAT_ID, "t": str(tid)})
            await db.execute(sql_text("""
                DELETE FROM orders WHERE lead_id IN (
                    SELECT l.id FROM leads l JOIN conversations cv ON cv.id = l.conversation_id
                    WHERE cv.telegram_chat_id = :cid
                )
            """), {"cid": CHAT_ID})
            await db.execute(sql_text("DELETE FROM leads WHERE conversation_id = :c"), {"c": str(c.id)})
            await db.execute(sql_text("DELETE FROM messages WHERE conversation_id = :c"), {"c": str(c.id)})
            await db.execute(sql_text("DELETE FROM conversations WHERE id = :c"), {"c": str(c.id)})
            await db.commit()
            print(f"{G}Clean!{X}\n")


if __name__ == "__main__":
    asyncio.run(run())
