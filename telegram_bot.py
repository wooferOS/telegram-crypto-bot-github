"""Telegram bot configuration and handlers."""

import os
from aiogram import Bot, Dispatcher, types
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", os.getenv("CHAT_ID", "0")))

if not TELEGRAM_TOKEN:
    raise RuntimeError("Missing TELEGRAM_TOKEN environment variable")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)


@dp.message_handler(commands=["zarobyty"])
async def handle_zarobyty(message: types.Message) -> None:
    """Minimal handler responding that the bot works and sees .env."""
    await message.answer("✅ Бот працює і бачить .env")

