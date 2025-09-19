"""General utility helpers for Binance Convert automation."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import random
import time


def floor_str_8(value: Decimal) -> str:
    """Return a string representation rounded down to 8 decimal places."""
    quantized = value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    as_str = format(quantized, "f")
    if "." in as_str:
        as_str = as_str.rstrip("0").rstrip(".")
    return as_str


def now_ms() -> int:
    """Return current UTC timestamp in milliseconds."""
    return int(time.time() * 1000)


def utc_now_hhmm() -> str:
    """Return current UTC time formatted as HH:MM."""
    return datetime.now(timezone.utc).strftime("%H:%M")


def within_utc_window(hhmm_from: str, hhmm_to: str) -> bool:
    """Return True if current UTC time is within the provided window."""
    current = utc_now_hhmm()
    cur_minutes = int(current[:2]) * 60 + int(current[3:])
    start_minutes = int(hhmm_from[:2]) * 60 + int(hhmm_from[3:])
    end_minutes = int(hhmm_to[:2]) * 60 + int(hhmm_to[3:])

    if start_minutes <= end_minutes:
        return start_minutes <= cur_minutes <= end_minutes
    return cur_minutes >= start_minutes or cur_minutes <= end_minutes


def sleep_jitter(seconds: int) -> float:
    """Sleep for a random delay between 0 and ``seconds`` seconds.

    The delay is returned so callers can include it in logs.  A non-positive
    ``seconds`` argument results in no delay and a return value of ``0.0``.
    """
    if seconds <= 0:
        return 0.0
    delay = random.uniform(0, float(seconds))
    time.sleep(delay)
    return delay
