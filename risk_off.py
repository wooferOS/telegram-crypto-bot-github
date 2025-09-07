import json
import os
from typing import Tuple

import requests

from convert_api import get_balances
from quote_counter import record_weight
from config_dev3 import MARKETDATA_BASE_URL

BASE_URL = MARKETDATA_BASE_URL
HIGH_FILE = os.path.join("logs", "portfolio_high.json")
DRAWDOWN_THRESHOLD = 0.10
PAUSE_THRESHOLD = 0.25


def _load_high() -> float:
    if os.path.exists(HIGH_FILE):
        try:
            with open(HIGH_FILE, "r", encoding="utf-8") as f:
                return float(json.load(f).get("high", 0))
        except Exception:
            return 0.0
    return 0.0


def _save_high(v: float) -> None:
    os.makedirs(os.path.dirname(HIGH_FILE), exist_ok=True)
    with open(HIGH_FILE, "w", encoding="utf-8") as f:
        json.dump({"high": v}, f)


def _price_usdt(asset: str) -> float:
    if asset == "USDT":
        return 1.0
    symbol = f"{asset}USDT"
    record_weight("avgPrice")
    try:
        r = requests.get(f"{BASE_URL}/api/v3/avgPrice", params={"symbol": symbol}, timeout=10)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except Exception:
        pass
    record_weight("ticker/24hr", 2)
    try:
        r = requests.get(f"{BASE_URL}/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=10)
        if r.status_code == 200:
            return float(r.json().get("lastPrice", 0))
    except Exception:
        pass
    return 0.0


def portfolio_value() -> float:
    try:
        balances = get_balances()
    except Exception:
        return 0.0
    total = 0.0
    for asset, amount in balances.items():
        px = _price_usdt(asset)
        total += amount * px
    return total


def check_risk() -> Tuple[int, float]:
    """Return (risk_level, drawdown)."""
    current = portfolio_value()
    if current <= 0:
        return 0, 0.0
    high = _load_high()
    if current > high:
        _save_high(current)
        high = current
    drawdown = (high - current) / high if high else 0.0
    if drawdown >= PAUSE_THRESHOLD:
        return 2, drawdown
    if drawdown >= DRAWDOWN_THRESHOLD:
        return 1, drawdown
    return 0, drawdown
