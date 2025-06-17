import logging
from typing import Iterable
from aiogram import Bot

from config import TELEGRAM_TOKEN

logger = logging.getLogger(__name__)


async def send_messages(chat_id: int, messages: Iterable[str]) -> None:
    """Send multiple messages to Telegram sequentially."""
    assert TELEGRAM_TOKEN, "TELEGRAM_TOKEN не може бути порожнім"
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        for text in messages:
            await bot.send_message(chat_id, text)
    finally:
        session = await bot.get_session()
        await session.close()
