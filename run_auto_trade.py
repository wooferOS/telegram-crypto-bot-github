"""Entry point for scheduled auto trade cycle with rate limiting."""

import asyncio
import json
import os
import time

from auto_trade_cycle import main
from config import TRADE_LOOP_INTERVAL

# Timestamp persistence file used to throttle automated runs
LAST_RUN_FILE = ".last_run.json"


def _should_run() -> bool:
    """Return ``True`` if enough time passed since the previous run."""
    if not os.path.exists(LAST_RUN_FILE):
        return True
    try:
        with open(LAST_RUN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        last = float(data.get("timestamp", 0))
    except Exception:
        return True
    return time.time() - last >= TRADE_LOOP_INTERVAL


def _store_run_time() -> None:
    """Persist current timestamp to ``LAST_RUN_FILE``."""
    try:
        with open(LAST_RUN_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time()}, f)
    except OSError:
        pass

if __name__ == "__main__":
    if _should_run():
        asyncio.run(main())
        _store_run_time()
