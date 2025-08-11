import json
import os
import time
from decimal import Decimal
from pathlib import Path
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
    if not symbol:
        return ""
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


# Єдине місце визначення шляху історії конверсій
HISTORY_PATH = Path("convert_history.json")


def safe_json_load(path: str | Path, default: Any) -> Any:
    p = Path(path)
    try:
        if not p.exists() or p.stat().st_size == 0:
            return default
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def safe_json_dump(path: str | Path, data: Any) -> None:
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
