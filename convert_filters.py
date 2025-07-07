from __future__ import annotations
import time
from typing import Dict, Tuple
from config_dev3 import MIN_NOTIONAL
from utils_dev3 import load_json
import json

HISTORY_FILE = "convert_history.json"


def check_filters(pair_data: dict) -> Tuple[bool, str]:
    if pair_data.get("score", 0) < 0.01:
        return False, "низький score"

    if pair_data.get("toAmount", 0) * pair_data.get("ratio", 0) < MIN_NOTIONAL:
        return False, "min_notional"

    history = load_json(HISTORY_FILE)
    for item in history:
        if item.get("from") == pair_data.get("from") and item.get("to") == pair_data.get("to"):
            return False, "duplicate"

    valid_until = float(pair_data.get("quote", {}).get("validTime", 0))
    if valid_until and valid_until < time.time() * 1000:
        return False, "quote_validity"

    return True, ""


def is_duplicate_conversion(from_token: str, to_token: str) -> bool:
    try:
        with open("convert_history.json", "r") as f:
            history = json.load(f)
        for entry in history:
            if entry.get("from") == from_token and entry.get("to") == to_token:
                return True
    except Exception:
        pass
    return False
