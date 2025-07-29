import json
import os
import time
from decimal import Decimal
from typing import Any


def safe_float(val: Any) -> float:
    """Return float value, handling nested dicts like {"value": x}."""
    if isinstance(val, dict):
        if "value" in val:
            val = val.get("value")
        elif "predicted" in val:
            val = val.get("predicted")
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("USDT", "")


def round_step_size(value: float, step: float) -> float:
    step_dec = Decimal(str(step))
    return float((Decimal(str(value)) // step_dec) * step_dec)


def format_amount(amount: float, precision: int = 6) -> str:
    return f"{amount:.{precision}f}".rstrip('0').rstrip('.')


def load_json(path: str) -> list | dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return [] if path.endswith(".json") else {}


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_current_timestamp() -> int:
    return int(time.time() * 1000)
