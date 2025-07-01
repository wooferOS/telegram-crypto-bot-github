"""Entry point for scheduled auto trade cycle with rate limiting."""

from datetime import datetime

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

import argparse
import asyncio
import json
import os
import time

import logging

from log_setup import setup_logging

from auto_trade_cycle import (
    main,
    generate_conversion_signals,
    load_gpt_filters,
    sell_unprofitable_assets,
)

from daily_analysis import generate_zarobyty_report
from binance_api import (
    get_symbol_price,
    get_binance_balances,
    refresh_valid_pairs,
    VALID_PAIRS,
)
from history import _load_history
from config import (
    TRADE_LOOP_INTERVAL,
    CHAT_ID,
    ADMIN_CHAT_ID,
)
from services.telegram_service import send_messages

logger = logging.getLogger(__name__)

# Ensure VALID_PAIRS is up to date before trading begins
refresh_valid_pairs()

# Minimum allowed interval between automated runs (1 hour)
MIN_AUTO_TRADE_INTERVAL = 3600
# Effective interval is the greater of the config value and our minimum
AUTO_INTERVAL = max(TRADE_LOOP_INTERVAL, MIN_AUTO_TRADE_INTERVAL)

# Timestamp persistence file used to throttle automated runs
LAST_RUN_FILE = ".last_run.json"


def _time_since_last_run() -> float:
    """Return seconds elapsed since the previous run."""
    if not os.path.exists(LAST_RUN_FILE):
        return AUTO_INTERVAL + 1
    try:
        with open(LAST_RUN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        last = float(data.get("timestamp", 0))
    except Exception:
        return AUTO_INTERVAL + 1
    return time.time() - last


def _store_run_time() -> None:
    """Persist current timestamp to ``LAST_RUN_FILE``."""
    try:
        with open(LAST_RUN_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time()}, f)
    except OSError:
        pass


def backtest() -> None:
    """Simple 24h backtest using recorded trade history."""
    history = _load_history()
    if not history:
        print("No trade history available")
        return
    successes = 0
    total = 0
    now = time.time()
    for item in history:
        ts = item.get("timestamp")
        if not ts:
            continue
        try:
            trade_time = datetime.fromisoformat(ts).timestamp()
        except Exception:
            continue
        if now - trade_time < 24 * 3600:
            continue
        symbol = item.get("symbol")
        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        price_now = get_symbol_price(pair)
        if not price_now:
            continue
        exp = float(item.get("expected_profit", 0))
        total += 1
        if item.get("action") == "buy":
            if price_now - item.get("price", 0) >= exp:
                successes += 1
        else:
            if item.get("price", 0) - price_now >= exp:
                successes += 1
    rate = successes / total * 100 if total else 0.0
    print(f"Backtest success rate: {successes}/{total} = {rate:.1f}%")

if __name__ == "__main__":
    def is_market_window_active():
        """Активні години ринку: 01:00–09:00 UTC (04:00–12:00 за Києвом)"""
        utc_hour = datetime.utcnow().hour
        return 1 <= utc_hour < 9

    if not is_market_window_active():
        logger.info("[dev] 💤 Ринок неактивний — трейд-цикл пропущено")
        raise SystemExit

    refresh_valid_pairs()
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", action="store_true", help="run backtest only")
    args = parser.parse_args()

    setup_logging()
    logger.info("[dev] ✅ VALID_PAIRS оновлено: %d пар", len(VALID_PAIRS))
    if not VALID_PAIRS:
        logger.error(
            "[dev] ❌ VALID_PAIRS порожній — неможливо отримати дані з Binance"
        )
        raise SystemExit(1)
    logger.info("[dev] 🚀 Автоматичний трейдинг запущено")

    if args.backtest:
        backtest()
        raise SystemExit

    # Sell assets with low expected profit before running the main cycle
    gpt_forecast = load_gpt_filters()
    gpt_filters = {
        "do_not_buy": gpt_forecast.get("do_not_buy", []),
        "recommend_buy": gpt_forecast.get("recommend_buy", []),
    }

    # Створити predictions.json, якщо він відсутній
    if not os.path.exists("predictions.json"):
        from daily_analysis import generate_zarobyty_report
        asyncio.run(generate_zarobyty_report())
    conversion_data = generate_conversion_signals(gpt_filters, gpt_forecast)
    gpt_forecast = conversion_data[-2]
    predictions = conversion_data[-1]


    portfolio = {
        asset: amt
        for asset, amt in get_binance_balances().items()
        if asset not in {"USDT", "BUSD"} and amt > 0
    }
    sold_before = sell_unprofitable_assets(portfolio, predictions, gpt_forecast)

    elapsed = _time_since_last_run()
    if elapsed >= AUTO_INTERVAL or sold_before:
        if elapsed < AUTO_INTERVAL and sold_before:
            logger.info("[dev] ⏱️ Запуск поза інтервалом через продаж активів")
        MAX_ATTEMPTS = 5
        attempt = 0
        summary = {"sold": [], "bought": []}

        sold: list[str] | None = []
        bought: list[str] | None = []

        while attempt < MAX_ATTEMPTS:
            summary = asyncio.run(main(int(ADMIN_CHAT_ID)))
            sold = summary.get("sold")
            bought = summary.get("bought")
            logger.info(
                f"[dev] Спроба {attempt + 1}: продано: {sold}, куплено: {bought}"
            )
            if sold or bought:
                break
            attempt += 1
            logger.info(f"[dev] ⏳ Спроба {attempt}: жодної угоди. Повторюємо...")

        _store_run_time()

        if summary.get("sold") or summary.get("bought"):
            lines = ["[dev] 🧾 Звіт:"]
            if summary.get("sold"):
                lines.append("\n🔁 Продано:")
                lines.extend(summary.get('sold'))
            if summary.get("bought"):
                lines.append("\n📈 Куплено:")
                lines.extend(summary.get('bought'))
            lines.append(f"\n💰 Баланс до: {summary.get('before', 0):.2f} USDT")
            lines.append(f"💰 Баланс після: {summary.get('after', 0):.2f} USDT")
            lines.append("\n✅ Завершено успішно.")
            asyncio.run(send_messages(int(CHAT_ID), ["\n".join(lines)]))
        else:
            logger.warning(
                "[dev] ❌ Після 5 спроб не вдалося виконати жодної угоди"
            )
    else:
        minutes = int(elapsed / 60)
        msg = (
            f"Автотрейд-цикл не запущено — останній запуск був {minutes} хвилин тому."
        )
        asyncio.run(send_messages(int(CHAT_ID), [msg]))
