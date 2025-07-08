import json
import os
import time
from datetime import datetime, timezone, timedelta

QUOTE_COUNT_FILE = os.path.join("logs", "quote_count.json")
QUOTE_LIMIT = 950


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


def increment_quote_usage() -> int:
    """Increment counter alias for clarity."""
    return increment()


def seconds_until_reset() -> float:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


def wait_until_reset() -> None:
    time.sleep(seconds_until_reset())
    _save({"date": _today(), "count": 0})
