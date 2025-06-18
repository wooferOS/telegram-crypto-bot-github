"""Entry point for scheduled auto trade cycle with rate limiting."""

import asyncio
import json
import os
import time

from auto_trade_cycle import main
from config import TRADE_LOOP_INTERVAL, CHAT_ID
from services.telegram_service import send_messages

# Timestamp persistence file used to throttle automated runs
LAST_RUN_FILE = ".last_run.json"


def _time_since_last_run() -> float:
    """Return seconds elapsed since the previous run."""
    if not os.path.exists(LAST_RUN_FILE):
        return TRADE_LOOP_INTERVAL + 1
    try:
        with open(LAST_RUN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        last = float(data.get("timestamp", 0))
    except Exception:
        return TRADE_LOOP_INTERVAL + 1
    return time.time() - last


def _store_run_time() -> None:
    """Persist current timestamp to ``LAST_RUN_FILE``."""
    try:
        with open(LAST_RUN_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time()}, f)
    except OSError:
        pass

if __name__ == "__main__":
    elapsed = _time_since_last_run()
    if elapsed >= TRADE_LOOP_INTERVAL:
        asyncio.run(main())
        _store_run_time()
    else:
        minutes = int(elapsed / 60)
        msg = f"Автотрейд-цикл не запущено — останній запуск був {minutes} хвилин тому."
        asyncio.run(send_messages(int(CHAT_ID), [msg]))
