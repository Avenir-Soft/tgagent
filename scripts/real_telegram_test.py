#!/usr/bin/env python3
"""
Real Telegram AI test — sends messages from @oybeff to @avenir_uz,
waits for AI responses, saves dialog to JSONL for fine-tuning.

Usage:
    python scripts/real_telegram_test.py --lang uz
    python scripts/real_telegram_test.py --lang ru --reset
    python scripts/real_telegram_test.py --export
"""
import asyncio
import argparse
import json
import sys
import os
import time
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient

API_ID = 33243468
API_HASH = "6aae610aaed24da144f980e0842cb4bd"
SESSION_PATH = "/tmp/oybeff_test"
STORE_USERNAME = "avenir_uz"

# ── Uzbek scenario (~75 messages) ──────────────────────────────────
UZ_MESSAGES = [
    # Phase 1: Greeting & Discovery (10)
    "Assalomu alaykum!",
    "Turlar haqida bilmoqchiman",
    "Qanday kategoriyalar bor sizlarda?",
    "Yengil yurish turlarini ko'rsating",
    "Eng arzon tur qaysi?",
    "Adrenalinli turlar bormi?",
    "Kemping turlari haqida gapirib bering",
    "Xalqaro turlar ham bormi?",
    "Ko'p kunlik turlar haqida aytib bering",
    "Eng mashhur turingiz qaysi?",

    # Phase 2: Deep dive — Paltau (15)
    "Paltau sharshara haqida batafsil ma'lumot bering",
    "Qaysi sanalar bor Paltau uchun?",
    "19-aprelda nechta joy qolgan?",
    "Yig'ilish joyi qayerda bo'ladi?",
    "Soat nechada yo'lga chiqamiz?",
    "Transport bilan boramizmi yoki o'zimiz kelamizmi?",
    "Narxga nimalar kiritilgan?",
    "Nima olib kelish kerak?",
    "Yo'lda qancha vaqt ketadi taxminan?",
    "Bolalar bilan borsa bo'ladimi? 7 yoshli bolam bor",
    "Yomg'ir yog'sa tur bekor bo'ladimi?",
    "Sharshara qanchalik baland?",
    "U yerda suzish mumkinmi?",
    "Yaxshi foto olish joylar bormi?",
    "Ovqat olib kelish kerakmi yoki kiritilganmi?",

    # Phase 3: Comparing tours (10)
    "Chukuraksu sharshara bilan Paltauning farqi nima?",
    "Qaysi biri yaxshiroq sizningcha?",
    "Tuzkon kemping qancha turadi?",
    "Tuzkon kempingda nima qilamiz kechqurun?",
    "Bungee jumping xavfli emasmi? Birinchi marta qilaman",
    "Zipline + Kayak haqida batafsil aytib bering",
    "Chimgan maliy turi nima o'zi?",
    "Mewa Party haqida gapirib bering",
    "Oqtosh tog' yurish qanday, qiyin emasmi?",
    "Qirg'iziston turi haqida batafsil ma'lumot bering",

    # Phase 4: Booking (12)
    "Paltau sharsharaga borishga qaror qildim!",
    "19-aprelga 2 kishiga bron qiling",
    "Ismim Dilshod, telefon raqamim 901112233",
    "Ha, hammasi to'g'ri, tasdiqlang",
    "To'lov qanday qilaman?",
    "Payme orqali to'layman",
    "Buyurtma raqamim nima edi?",
    "Buyurtma holatini tekshiring",
    "Yana bitta do'stim qo'shilmoqchi, 3 kishiga o'zgartirsa bo'ladimi?",
    "Bungee jumpingga ham bron qilmoqchiman, 20-aprelga 2 kishi",
    "Ismim Dilshod, telefon 901112233",
    "Ha, to'g'ri, tasdiqlang",

    # Phase 5: Post-booking (12)
    "Ikkala buyurtmam holatini ko'rsating",
    "Paltau buyurtmamni bekor qilsam bo'ladimi?",
    "Yo'q yo'q, bekor qilmang, albatta boraman",
    "Bungee jumping uchun maxsus kiyim kerakmi?",
    "Krossovka kiyib borsam bo'ladimi?",
    "Sertifikat berishadimi bungee jumpingdan keyin?",
    "Do'stlarimga tavsiya qilsam chegirma bormi?",
    "5 kishiga guruh chegirmasi bormi?",
    "Qaysi turlar eng tez band bo'ladi?",
    "Operator bilan gaplashsam bo'ladimi?",
    "Yo'q, kerak emas, o'zingiz yaxshi javob beryapsiz",
    "Tuzkon kempingga keyingi oy bormoqchiman, joylar bormi?",

    # Phase 6: Edge cases & off-topic (10)
    "Dubayga turlar bormi sizlarda?",
    "2 ta 2 ni qo'shsak nechta bo'ladi?",
    "19-aprelda ob-havo qanday bo'ladi?",
    "Ishlaysizlarmi hozir? Kech bo'lib qoldi",
    "Suv olib kelish kerakmi yoki beraverasizlarmi?",
    "Instagram sahifangiz bormi? Rasm ko'rmoqchiman",
    "Boshqa agentlik 150 ming deyapti, sizda nega 199 ming?",
    "Nima uchun sizlarni tanlashim kerak?",
    "Bank rekvizitlarini bersangiz to'lab qo'yaman",
    "Rahmat, juda yaxshi xizmat ko'rsatyapsiz!",

    # Phase 7: Final (6)
    "Mening barcha buyurtmalarim haqida ma'lumot bering",
    "Paltau uchun do'stimga ham joy bron qilmoqchiman",
    "26-aprelga 1 kishi, ismi Jasur, telefon 907778899",
    "Ha, tasdiqlang",
    "Juda zo'r, rahmat! 19-aprelda ko'rishamiz!",
    "Xayr!",
]

# ── Russian scenario (~75 messages) ──────────────────────────────
RU_MESSAGES = [
    # Phase 1: Greeting (8)
    "Здравствуйте!",
    "Расскажите про ваши туры",
    "Какие категории есть?",
    "Покажите лёгкие туры для новичков",
    "А какой самый дешёвый тур?",
    "Есть экстремальные туры?",
    "Кемпинг есть?",
    "А за границу есть туры?",

    # Phase 2: Details Paltau (15)
    "Расскажите подробнее про водопад Палтау",
    "Какие даты доступны?",
    "На 19 апреля сколько мест осталось?",
    "Где место сбора?",
    "Во сколько выезд?",
    "Транспорт включён или самим добираться?",
    "Что входит в стоимость?",
    "Что с собой брать?",
    "Сколько времени в дороге?",
    "Можно с детьми? У меня сын 8 лет",
    "Если будет дождь, тур отменяется?",
    "Водопад высокий?",
    "Можно купаться?",
    "Еду с собой брать или кормят?",
    "Там сигнал сотовой связи есть?",

    # Phase 3: Comparing (12)
    "Чем отличается Чукуракcу от Палтау?",
    "Какой водопад лучше для фотографий?",
    "Сколько стоит кемпинг Тузкон?",
    "А что делать вечером на кемпинге?",
    "Расскажите про банджи джампинг подробнее",
    "Это безопасно? Страшно немного",
    "Зиплайн + каяк — это за один день?",
    "Что такое Чимган малый?",
    "Расскажите про Мева Пати",
    "Окташ — это сложный маршрут?",
    "Кыргызстан тур — виза нужна?",
    "Сколько стоит Кыргызстан?",

    # Phase 4: Booking (12)
    "Хочу забронировать Палтау на 26 апреля",
    "На 3 человека",
    "Меня зовут Алексей, телефон 909998877",
    "Да, всё верно, подтверждаю",
    "Как оплатить?",
    "Оплачу через Click",
    "Напомните номер заказа",
    "Какой статус моего заказа?",
    "А можно добавить ещё одного человека?",
    "Хочу также забронировать зиплайн",
    "На 27 апреля, 2 человека, Алексей, 909998877",
    "Да, подтверждаю",

    # Phase 5: Post-booking (12)
    "Покажите все мои заказы",
    "Можно отменить заказ на Палтау?",
    "Нет, не отменяйте, я еду обязательно",
    "Что надеть на зиплайн?",
    "Перчатки нужны?",
    "Каяк — это сложно для новичка?",
    "Инструктор будет?",
    "Скидка есть для групп больше 5 человек?",
    "Какой тур самый популярный у вас?",
    "Можно поговорить с оператором?",
    "Не нужно, вы хорошо помогаете",
    "На следующей неделе есть Тузкон кемпинг?",

    # Phase 6: Edge cases (10)
    "А в Дубай туры есть?",
    "Сколько будет 3 умножить на 5?",
    "Какая погода будет 26 апреля?",
    "Вы сейчас работаете? Уже поздно",
    "Воду брать с собой или дадите?",
    "У вас есть инстаграм?",
    "В другом агентстве дешевле, почему у вас дороже?",
    "Почему стоит выбрать именно вас?",
    "Дайте реквизиты для перевода",
    "Спасибо, отличный сервис!",

    # Phase 7: Final (6)
    "Покажите информацию по всем моим бронированиям",
    "Хочу забронировать Тузкон кемпинг для друга",
    "На 19-20 апреля, 1 человек, Марат, телефон 905554433",
    "Да, подтверждаю",
    "Отлично! Увидимся 26 апреля на Палтау!",
    "До свидания!",
]


async def send_and_wait(client, entity, message: str, wait_sec: int = 10) -> list[dict]:
    """Send message and wait for AI response(s)."""
    # Get last message ID before sending
    msgs_before = await client.get_messages(entity, limit=1)
    last_id = msgs_before[0].id if msgs_before else 0

    # Send
    await client.send_message(entity, message)
    sent_time = time.time()

    # Wait for response
    await asyncio.sleep(wait_sec)

    # Poll for new messages (AI might send multiple)
    responses = []
    for attempt in range(5):  # retry if AI hasn't responded yet
        new_msgs = await client.get_messages(entity, limit=10, min_id=last_id)
        # Filter: only incoming (from AI), not our sent message
        ai_msgs = [m for m in new_msgs if not m.out and m.id > last_id]

        if ai_msgs:
            for m in sorted(ai_msgs, key=lambda x: x.id):
                resp = {
                    "text": m.text or "",
                    "media": None,
                    "message_id": m.id,
                    "date": m.date.isoformat(),
                }
                if m.media:
                    resp["media"] = str(type(m.media).__name__)
                responses.append(resp)
            break
        else:
            # Wait more
            await asyncio.sleep(5)

    elapsed = time.time() - sent_time
    return responses, elapsed


async def reset_conversation(store_username: str):
    """Reset conversation via API so AI forgets previous dialog."""
    import aiohttp

    # Login to get JWT
    async with aiohttp.ClientSession() as session:
        login_resp = await session.post(
            "http://localhost:8001/auth/login",
            json={"email": "admin@gmail.com", "password": "admin"},
        )
        token = (await login_resp.json())["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Find conversation for @oybeff
        convs_resp = await session.get(
            "http://localhost:8001/conversations",
            headers=headers,
        )
        convs = await convs_resp.json()

        for conv in convs:
            username = (conv.get("customer_username") or "").lower()
            if "oybeff" in username or "oybek" in username.lower():
                conv_id = conv["id"]
                # Reset conversation
                reset_resp = await session.post(
                    f"http://localhost:8001/conversations/{conv_id}/reset",
                    headers=headers,
                )
                if reset_resp.status == 200:
                    print(f"  ✅ Conversation {conv_id} reset!")
                else:
                    print(f"  ❌ Reset failed: {reset_resp.status}")
                return conv_id

    print("  ⚠️ No conversation found for @oybeff")
    return None


async def run_scenario(lang: str, messages: list[str]):
    """Run a full scenario and collect dialog."""
    print(f"\n{'='*70}")
    print(f"  REAL TELEGRAM TEST — {lang.upper()} ({len(messages)} messages)")
    print(f"{'='*70}\n")

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        print("❌ Not authorized! Run scripts/login_mcp_telegram.py first")
        return

    me = await client.get_me()
    print(f"  Logged in as: {me.first_name} (@{me.username})")

    entity = await client.get_entity(STORE_USERNAME)
    print(f"  Sending to: {entity.first_name} (@{entity.username})")
    print()

    dialog = []  # Collect for JSONL
    passed = 0
    failed = 0
    start_time = time.time()

    for i, msg in enumerate(messages, 1):
        # Print outgoing
        short_msg = msg[:80] + "..." if len(msg) > 80 else msg
        print(f"  \033[2m#{i:>3}\033[0m \033[1m>\033[0m {short_msg}")

        try:
            responses, elapsed = await send_and_wait(client, entity, msg, wait_sec=8)

            if responses:
                # Combine multi-message responses
                full_response = "\n".join(r["text"] for r in responses if r["text"])
                media_count = sum(1 for r in responses if r["media"])

                short_resp = full_response[:100].replace("\n", " ↵ ")
                if len(full_response) > 100:
                    short_resp += "..."

                media_note = f" +{media_count} media" if media_count else ""
                print(f"  \033[2m#{i:>3}\033[0m  \033[96m<\033[0m {short_resp} \033[2m({elapsed:.1f}s{media_note})\033[0m")

                dialog.append({"role": "user", "content": msg})
                dialog.append({"role": "assistant", "content": full_response})
                passed += 1
            else:
                print(f"  \033[2m#{i:>3}\033[0m  \033[91m< NO RESPONSE ({elapsed:.1f}s)\033[0m")
                dialog.append({"role": "user", "content": msg})
                dialog.append({"role": "assistant", "content": "[NO RESPONSE]"})
                failed += 1

        except Exception as e:
            print(f"  \033[91m  ✗ Error: {e}\033[0m")
            failed += 1

    total_time = time.time() - start_time

    await client.disconnect()

    # Save JSONL
    output_file = f"data/{lang}_dialog_{datetime.now().strftime('%Y%m%d_%H%M')}.jsonl"
    os.makedirs("data", exist_ok=True)

    # System prompt for fine-tuning
    system_msg = {
        "role": "system",
        "content": (
            "Siz Easy Tour / Oson Turizm sayohat agentligining AI yordamchisisiz. "
            "Faqat turlar haqida gaplashing. Mijozga tur tanlashda, bronlashda va "
            "to'lov qilishda yordam bering. Doim odobli va qisqa javob bering."
            if lang == "uz" else
            "Вы AI-помощник туристического агентства Easy Tour / Oson Turizm. "
            "Говорите только о турах. Помогайте клиенту выбрать тур, забронировать "
            "и оплатить. Всегда отвечайте вежливо и кратко."
        ),
    }

    # Write as single training example
    training_example = {"messages": [system_msg] + dialog}
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(training_example, ensure_ascii=False) + "\n")

    # Also save raw dialog for readability
    raw_file = f"data/{lang}_dialog_{datetime.now().strftime('%Y%m%d_%H%M')}_raw.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(dialog, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*70}")
    print(f"  RESULTS: {passed}/{len(messages)} responses, {failed} failures")
    print(f"  Total time: {total_time/60:.1f} min")
    print(f"  JSONL saved: {output_file}")
    print(f"  Raw dialog: {raw_file}")
    print(f"{'='*70}\n")

    return output_file


async def export_both():
    """Show saved JSONL files."""
    if not os.path.exists("data"):
        print("No data/ directory found. Run scenarios first.")
        return
    files = sorted(f for f in os.listdir("data") if f.endswith(".jsonl"))
    for f in files:
        path = os.path.join("data", f)
        size = os.path.getsize(path)
        with open(path) as fh:
            data = json.loads(fh.readline())
            msg_count = len(data["messages"]) - 1  # minus system
        print(f"  {f} — {msg_count} messages, {size/1024:.1f} KB")


async def main():
    parser = argparse.ArgumentParser(description="Real Telegram AI test")
    parser.add_argument("--lang", choices=["uz", "ru"], help="Language scenario")
    parser.add_argument("--reset", action="store_true", help="Reset conversation before test")
    parser.add_argument("--export", action="store_true", help="Show saved JSONL files")
    parser.add_argument("--both", action="store_true", help="Run both scenarios (uz then ru with reset)")
    args = parser.parse_args()

    if args.export:
        await export_both()
        return

    if args.both:
        # Run Uzbek
        await run_scenario("uz", UZ_MESSAGES)
        # Reset conversation
        print("\n🔄 Resetting conversation for Russian scenario...\n")
        await reset_conversation(STORE_USERNAME)
        await asyncio.sleep(3)
        # Run Russian
        await run_scenario("ru", RU_MESSAGES)
        await export_both()
        return

    if args.lang:
        if args.reset:
            print("🔄 Resetting conversation...")
            await reset_conversation(STORE_USERNAME)
            await asyncio.sleep(3)

        messages = UZ_MESSAGES if args.lang == "uz" else RU_MESSAGES
        await run_scenario(args.lang, messages)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
