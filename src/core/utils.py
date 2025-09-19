"""Utility helpers shared across Convert automation modules."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Tuple

import time


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


def _extract_limits(exchange_info: dict) -> Tuple[Decimal, Decimal]:
    payload: Any = exchange_info
    if isinstance(exchange_info, dict) and "data" in exchange_info:
        payload = exchange_info.get("data", {})
    min_raw = None if not isinstance(payload, dict) else payload.get("fromAssetMinAmount")
    max_raw = None if not isinstance(payload, dict) else payload.get("fromAssetMaxAmount")
    return _to_decimal(min_raw), _to_decimal(max_raw)


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def ensure_amount_and_limits(exchange_info: dict, amount_dec: Decimal) -> None:
    """Validate that ``amount_dec`` is inside Convert min/max limits."""

    minimum, maximum = _extract_limits(exchange_info)
    if minimum > 0 and amount_dec < minimum:
        raise ValueError(f"amount {amount_dec} below minimum {minimum}")
    if maximum > 0 and amount_dec > maximum:
        raise ValueError(f"amount {amount_dec} above maximum {maximum}")
