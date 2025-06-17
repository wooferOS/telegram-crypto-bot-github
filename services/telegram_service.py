import logging
from typing import Iterable
from aiogram import Bot

DEV_TAG = "[dev]"


def _format_dev_message(text: str) -> str:
    """Insert ``[dev]`` tag into the outgoing ``text``."""
    if DEV_TAG in text:
        return text
    markers = ("⚠️", "✅", "🔁", "ℹ️", "❌")
    for m in markers:
        if text.startswith(m):
            return f"{m} {DEV_TAG} {text[len(m):].lstrip()}"
    return f"{DEV_TAG} {text}"


class DevBot(Bot):
    """Bot that automatically appends ``[dev]`` to all messages."""

    async def send_message(self, chat_id: int, text: str, *args, **kwargs):
        text = _format_dev_message(text)
        return await super().send_message(chat_id, text, *args, **kwargs)

from config import TELEGRAM_TOKEN

logger = logging.getLogger(__name__)


_last_message: str | None = None


async def send_messages(chat_id: int, messages: Iterable[str]) -> None:
    """Send multiple messages to Telegram sequentially, skipping duplicates."""
    assert TELEGRAM_TOKEN, "TELEGRAM_TOKEN не може бути порожнім"
    bot = DevBot(token=TELEGRAM_TOKEN)
    global _last_message
    try:
        for text in messages:
            if not text.strip():
                continue
            if text == _last_message:
                continue
            await bot.send_message(chat_id, text)
            _last_message = text
    finally:
        session = await bot.get_session()
        await session.close()
