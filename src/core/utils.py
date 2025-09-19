"""General utility helpers for Binance Convert automation."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import random
import time


def now_ms() -> int:
    """Return the current UTC timestamp in milliseconds."""

    return int(time.time() * 1000)


def utc_fmt(ms: int) -> str:
    """Format a millisecond UTC timestamp into a readable string."""

    seconds, _ = divmod(int(ms), 1000)
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def sleep_jitter(min_ms: int, max_ms: int) -> float:
    """Sleep for a random delay between ``min_ms`` and ``max_ms`` milliseconds."""

    if max_ms <= 0:
        return 0.0

    if min_ms < 0:
        min_ms = 0

    if max_ms < min_ms:
        min_ms, max_ms = max_ms, min_ms

    delay = random.uniform(float(min_ms), float(max_ms)) / 1000.0
    if delay > 0:
        time.sleep(delay)
    return delay


def floor_str_8(value: Decimal) -> str:
    """Return a string representation rounded down to eight decimal places."""

    quantized = value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    as_str = format(quantized, "f")
    if "." in as_str:
        as_str = as_str.rstrip("0").rstrip(".")
    return as_str or "0"
