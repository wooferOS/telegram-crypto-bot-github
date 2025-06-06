"""Helpers for calculating profit statistics for the bot."""

import logging
from datetime import datetime, timedelta
from typing import List, Dict

from binance_api import get_usdt_to_uah_rate
from history import _load_history

logger = logging.getLogger(__name__)


def _filter_trades(days: int) -> List[Dict]:
    history = _load_history()
    cutoff = datetime.utcnow() - timedelta(days=days)
    return [t for t in history if datetime.fromisoformat(t["timestamp"]) >= cutoff]


def _calculate_profit(trades: List[Dict]) -> float:
    last_buy = {}
    profit = 0.0
    for t in trades:
        symbol = t["symbol"]
        price = float(t["price"])
        qty = float(t["qty"])
        if t["side"].upper() == "BUY":
            last_buy[symbol] = price
        elif t["side"].upper() == "SELL" and symbol in last_buy:
            profit += (price - last_buy[symbol]) * qty
            last_buy[symbol] = price
    return profit


def generate_stats_report() -> str:
    week_profit = _calculate_profit(_filter_trades(7))
    month_profit = _calculate_profit(_filter_trades(30))
    rate = get_usdt_to_uah_rate()
    report = (
        f"\U0001F4C8 \u041F\u0440\u0438\u0431\u0443\u0442\u043E\u043A \u0437\u0430 \u0442\u0438\u0436\u0434\u0435\u043D\u044C: {week_profit:.2f} USDT (~{week_profit * rate:.2f}\u20b4)\n"
        f"\U0001F4C8 \u041F\u0440\u0438\u0431\u0443\u0442\u043E\u043A \u0437\u0430 \u043C\u0456\u0441\u044F\u0446\u044C: {month_profit:.2f} USDT (~{month_profit * rate:.2f}\u20b4)"
    )
    return report



def calculate_stats() -> str:
    """Return day, week and month profit summary for Telegram."""
    day = _calculate_profit(_filter_trades(1))
    week = _calculate_profit(_filter_trades(7))
    month = _calculate_profit(_filter_trades(30))
    rate = get_usdt_to_uah_rate()
    return (
        "\U0001F4C8 \u041F\u0456\u0434\u0441\u0443\u043C\u043E\u043A:\n"
        f"\u0414\u0435\u043D\u044C: {day:.2f} USDT (~{day * rate:.2f}\u20B4)\n"
        f"\u0422\u0438\u0436\u0434\u0435\u043D\u044C: {week:.2f} USDT (~{week * rate:.2f}\u20B4)\n"
        f"\u041C\u0456\u0441\u044F\u0446\u044C: {month:.2f} USDT (~{month * rate:.2f}\u20B4)"
    )
