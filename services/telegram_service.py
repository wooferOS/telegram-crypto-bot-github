import logging
from typing import Iterable
from aiogram import Bot

logger = logging.getLogger(__name__)


async def send_messages(token: str, chat_id: int, messages: Iterable[str]) -> None:
    """Send multiple messages to Telegram sequentially."""
    bot = Bot(token=token)
    try:
        for text in messages:
            await bot.send_message(chat_id, text)
    finally:
        session = await bot.get_session()
        await session.close()
