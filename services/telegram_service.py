import logging
from typing import Iterable
import os
import json
import time
import hashlib
from aiogram import Bot
import aiohttp

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

from config import (
    TELEGRAM_TOKEN,
)

logger = logging.getLogger(__name__)


# Persist last sent message hash and timestamp to avoid repeated alerts
LAST_MESSAGE_FILE = os.path.join("logs", "last_message_hash.txt")
_last_data: dict[str, object] = {"hash": None, "time": 0.0}

if os.path.exists(LAST_MESSAGE_FILE):
    try:
        with open(LAST_MESSAGE_FILE, "r", encoding="utf-8") as f:
            _last_data = json.load(f)
    except OSError as exc:  # pragma: no cover - diagnostics only
        logger.warning("Could not read %s: %s", LAST_MESSAGE_FILE, exc)


async def send_messages(chat_id: int, messages: list[str]):
    token = TELEGRAM_TOKEN
    if not token or not chat_id:
        return

    async with aiohttp.ClientSession() as session:
        for msg in messages:
            try:
                await session.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg},
                    timeout=aiohttp.ClientTimeout(total=10),
                )
            except Exception as exc:
                logger.warning(
                    "❌ Не вдалося надіслати повідомлення Telegram: %s", exc
                )
