import json
import os
import time
from datetime import datetime, timezone, timedelta
import logging

from convert_logger import logger

QUOTE_COUNT_FILE = os.path.join("logs", "quote_count.json")
QUOTE_LIMIT = 950
MAX_PER_CYCLE = 20

_cycle_count = 0


def _load() -> dict:
    if os.path.exists(QUOTE_COUNT_FILE):
        with open(QUOTE_COUNT_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def _save(data: dict) -> None:
    os.makedirs("logs", exist_ok=True)
    with open(QUOTE_COUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_count() -> int:
    data = _load()
    today = _today()
    if data.get("date") != today:
        data = {"date": today, "count": 0}
        _save(data)
        return 0
    return int(data.get("count", 0))


def increment() -> int:
    today = _today()
    data = _load()
    if data.get("date") != today:
        data = {"date": today, "count": 1}
    else:
        data["count"] = int(data.get("count", 0)) + 1
    _save(data)
    return data["count"]


def record_cycle_request() -> None:
    """Increment per-cycle quote counter."""
    global _cycle_count
    _cycle_count += 1


def reset_cycle() -> None:
    """Reset per-cycle counter (should be called at the start of a cycle)."""
    global _cycle_count
    _cycle_count = 0


def increment_quote_usage() -> int:
    """Increment counter alias for clarity."""
    record_cycle_request()
    return increment()


def can_request_quote() -> bool:
    """Return True if current quote count is below the limit."""
    return get_count() < QUOTE_LIMIT


def should_throttle(from_token: str = "", to_token: str = "", response: dict | None = None) -> bool:
    """Return True if quote requests should be throttled."""
    global _cycle_count

    if response and isinstance(response, dict) and response.get("code") == 345239:
        logger.warning(
            "[dev3] 🟥 Ліміт Binance Convert API досягнуто (code=345239)"
        )
        return True

    if get_count() >= QUOTE_LIMIT:
        logger.warning(
            "[dev3] ⛔ Добовий ліміт Convert API перевищено — пропуск %s → %s",
            from_token,
            to_token,
        )
        return True

    if _cycle_count >= MAX_PER_CYCLE:
        logger.warning(
            "[dev3] ⏸️ Ліміт %s quote за цикл перевищено — пропуск %s → %s",
            MAX_PER_CYCLE,
            from_token,
            to_token,
        )
        return True

    return False


def seconds_until_reset() -> float:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


def wait_until_reset() -> None:
    time.sleep(seconds_until_reset())
    _save({"date": _today(), "count": 0})
