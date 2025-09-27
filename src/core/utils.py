"""Utility helpers shared across Convert automation modules."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Iterable, Tuple

import math
import random
import time


DECIMAL_ZERO = Decimal("0")


def now_ms() -> int:
    """Return the current UTC timestamp in milliseconds."""

    return int(time.time() * 1000)


def utc_fmt(ms: int) -> str:
    """Format milliseconds since epoch into an UTC timestamp string."""

    seconds, _ = divmod(int(ms), 1000)
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def floor_str_8(value: Decimal) -> str:
    """Return a decimal string rounded down to eight decimal places."""

    quantized = value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    as_str = format(quantized, "f")
    if "." in as_str:
        as_str = as_str.rstrip("0").rstrip(".")
    return as_str or "0"


def decimal_from_any(value: Any, default: Decimal | None = None) -> Decimal:
    """Coerce *value* into :class:`~decimal.Decimal`.

    ``default`` is returned when *value* cannot be represented as a Decimal.
    """

    if value is None:
        return DECIMAL_ZERO if default is None else default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return DECIMAL_ZERO if default is None else default


def clamp(value: float, lower: float, upper: float) -> float:
    """Return ``value`` constrained to ``[lower, upper]``."""

    return max(lower, min(upper, value))


def rolling_log_directory(base: str, ts: float | None = None) -> Path:
    """Return the per-day log directory creating it if necessary."""

    ts = ts or time.time()
    day = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    path = Path(base).expanduser().resolve() / day
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path) -> None:
    """Create parent directory for *path* if missing."""

    path.parent.mkdir(parents=True, exist_ok=True)


def rand_jitter(seconds_range: Iterable[float] | None) -> float:
    """Return a random jitter duration in seconds."""

    if not seconds_range:
        return 0.0
    seq = tuple(seconds_range)
    if not seq:
        return 0.0
    if len(seq) == 1:
        return float(seq[0])
    low = float(seq[0])
    high = float(seq[-1])
    if math.isclose(low, high):
        return low
    return random.uniform(min(low, high), max(low, high))


def _extract_limits(exchange_info: dict) -> Tuple[Decimal, Decimal]:
    payload: Any = exchange_info
    if isinstance(exchange_info, dict) and "data" in exchange_info:
        payload = exchange_info.get("data", {})
    min_raw = None if not isinstance(payload, dict) else payload.get("fromAssetMinAmount")
    max_raw = None if not isinstance(payload, dict) else payload.get("fromAssetMaxAmount")
    return decimal_from_any(min_raw), decimal_from_any(max_raw)


def ensure_amount_and_limits(exchange_info: dict, amount_dec: Decimal) -> None:
    """Validate that ``amount_dec`` is inside Convert min/max limits."""

    minimum, maximum = _extract_limits(exchange_info)
    if minimum > 0 and amount_dec < minimum:
        raise ValueError(f"amount {amount_dec} below minimum {minimum}")
    if maximum > 0 and amount_dec > maximum:
        raise ValueError(f"amount {amount_dec} above maximum {maximum}")
