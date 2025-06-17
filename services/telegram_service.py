from aiogram import Bot
from config import TELEGRAM_TOKEN

async def send_messages(chat_id: int, text: str) -> None:
    """Send a text message via Telegram using the global token."""

    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id, text)
