"""Simple storage helpers for keeping trade history."""

import json
import os
import logging
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)
HISTORY_FILE = "trade_history.json"


def _load_history() -> List[Dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to read history: %s", exc)
    return []


def _save_history(data: List[Dict]) -> None:
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("Failed to save history: %s", exc)


def add_trade(symbol: str, side: str, qty: float, price: float, timestamp: str | None = None) -> None:
    history = _load_history()
    history.append(
        {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "timestamp": timestamp or datetime.utcnow().isoformat(),
        }
    )
    _save_history(history)


def generate_history_report() -> str:
    history = _load_history()
    if not history:
        return "\u041d\u0435\u043c\u0430\u0454 \u0456\u0441\u0442\u043e\u0440\u0456\u0457 \u0443\u0433\u043e\u0434."

    lines = []
    for item in history:
        dt = item["timestamp"].split("T")[0]
        lines.append(f"{dt} {item['symbol']} {item['side']} {item['qty']} @ {item['price']}")
    return "\U0001F4C3 \u0406\u0441\u0442\u043E\u0440\u0456\u044F \u0443\u0433\u043E\u0434:\n" + "\n".join(lines)



def get_trade_history() -> str:
    """Return formatted trade history for the /history command."""
    try:
        return generate_history_report()
    except Exception as exc:
        logger.error("Failed to prepare trade history: %s", exc)
        return "History unavailable."


def get_failed_tokens_history(threshold: float = -1.0) -> set[str]:
    """Return set of symbols with historical profit below ``threshold`` percent."""

    history = _load_history()
    by_symbol: dict[str, list[tuple[str, float, float]]] = {}
    for item in history:
        sym = str(item.get("symbol", "")).upper()
        side = str(item.get("side", "")).upper()
        qty = float(item.get("qty", 0))
        price = float(item.get("price", 0))
        by_symbol.setdefault(sym, []).append((side, qty, price))

    failed: set[str] = set()
    for sym, trades in by_symbol.items():
        profit = 0.0
        last_buy = None
        for side, qty, price in trades:
            if side == "BUY":
                last_buy = price
            elif side == "SELL" and last_buy:
                profit += (price - last_buy) / last_buy * 100
                last_buy = None
        if profit < threshold:
            failed.add(sym)
    return failed
