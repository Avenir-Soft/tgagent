#!/usr/bin/env python3
"""Login to Telegram for MCP server (interactive)."""
import asyncio
from telethon import TelegramClient

API_ID = 33243468
API_HASH = "6aae610aaed24da144f980e0842cb4bd"
SESSION_PATH = "/Users/macbook/.local/state/mcp-telegram/session"

async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()

    phone = input("Телефон (e.g. +998977061605): ").strip()

    result = await client.send_code_request(phone)
    print(f"\n✅ Код отправлен! Тип: {result.type.__class__.__name__}")
    print("Проверь Telegram — код придёт как сообщение от 'Telegram'\n")

    code = input("Введи код: ").strip()

    try:
        await client.sign_in(phone, code)
    except Exception as e:
        if "Two-steps verification" in str(e) or "password" in str(e).lower():
            password = input("2FA пароль: ").strip()
            await client.sign_in(password=password)
        else:
            raise

    me = await client.get_me()
    print(f"\n✅ Залогинен как: {me.first_name} (@{me.username})")
    print(f"Сессия сохранена: {SESSION_PATH}.session")

    await client.disconnect()

asyncio.run(main())
