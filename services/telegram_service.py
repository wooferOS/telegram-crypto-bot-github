import logging
from typing import Iterable
from aiogram import Bot
import os
import hashlib

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


# Persist last sent message hash to avoid repeated alerts across restarts
LAST_MESSAGE_FILE = os.path.join("logs", "last_message_hash.txt")
_last_hash: str | None = None

if os.path.exists(LAST_MESSAGE_FILE):
    try:
        with open(LAST_MESSAGE_FILE, "r", encoding="utf-8") as f:
            _last_hash = f.read().strip() or None
    except OSError as exc:  # pragma: no cover - diagnostics only
        logger.warning("Could not read %s: %s", LAST_MESSAGE_FILE, exc)


async def send_messages(chat_id: int, messages: Iterable[str]) -> None:
    """Send multiple messages to Telegram sequentially, skipping duplicates."""
    assert TELEGRAM_TOKEN, "TELEGRAM_TOKEN не може бути порожнім"
    bot = DevBot(token=TELEGRAM_TOKEN)
    global _last_hash
    texts = [m.strip() for m in messages if m.strip()]
    if not texts:
        return
    try:
        for text in texts:
            msg_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
            if msg_hash == _last_hash:
                continue
            await bot.send_message(chat_id, text)
            _last_hash = msg_hash
            try:
                os.makedirs(os.path.dirname(LAST_MESSAGE_FILE), exist_ok=True)
                with open(LAST_MESSAGE_FILE, "w", encoding="utf-8") as f:
                    f.write(_last_hash)
            except OSError as exc:  # pragma: no cover - diagnostics only
                logger.warning("Could not write %s: %s", LAST_MESSAGE_FILE, exc)
    finally:
        session = await bot.get_session()
        await session.close()
