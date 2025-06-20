"""Entry point for scheduled auto trade cycle with rate limiting."""

import argparse
import asyncio
import json
import os
import time
from datetime import datetime

import logging

from log_setup import setup_logging

from auto_trade_cycle import (
    main,
    generate_conversion_signals,
    load_gpt_filters,
    sell_unprofitable_assets,
)
from binance_api import get_symbol_price, get_binance_balances
from history import _load_history
from config import TRADE_LOOP_INTERVAL, CHAT_ID
from services.telegram_service import send_messages

logger = logging.getLogger(__name__)

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", action="store_true", help="run backtest only")
    args = parser.parse_args()

    setup_logging()

    if args.backtest:
        backtest()
        raise SystemExit

    # Sell assets with low expected profit before running the main cycle
    gpt_forecast = load_gpt_filters()
    gpt_filters = {"do_not_sell": gpt_forecast.get("sell", [])}
    (
        _,
        _,
        _,
        _,
        _,
        _,
        gpt_forecast,
        predictions,
    ) = generate_conversion_signals(gpt_filters, gpt_forecast)
    portfolio = {
        asset: amt
        for asset, amt in get_binance_balances().items()
        if asset not in {"USDT", "BUSD"} and amt > 0
    }
    sell_unprofitable_assets(portfolio, predictions, gpt_forecast)

    elapsed = _time_since_last_run()
    if elapsed >= AUTO_INTERVAL:
        summary = asyncio.run(main(int(CHAT_ID)))
        if not summary["sold"] and not summary["bought"]:
            logger.warning("[dev] ❗ Увага: трейд-цикл завершився без активних дій")
            asyncio.run(
                send_messages(
                    int(CHAT_ID),
                    [
                        "[dev] ❗ Увага: жодного продажу чи купівлі не відбулося. Можливо, не спрацювали фільтри."
                    ],
                )
            )
        _store_run_time()
        lines = ["[dev] 🧾 Звіт:"]
        if summary.get("sold"):
            lines.append("\n🔁 Продано:")
            lines.extend(summary["sold"])
        if summary.get("bought"):
            lines.append("\n📈 Куплено:")
            lines.extend(summary["bought"])
        lines.append(f"\n💰 Баланс до: {summary.get('before', 0):.2f} USDT")
        lines.append(f"💰 Баланс після: {summary.get('after', 0):.2f} USDT")
        lines.append("\n✅ Завершено успішно.")
        asyncio.run(send_messages(int(CHAT_ID), ["\n".join(lines)]))
    else:
        minutes = int(elapsed / 60)
        msg = (
            f"Автотрейд-цикл не запущено — останній запуск був {minutes} хвилин тому."
        )
        asyncio.run(send_messages(int(CHAT_ID), [msg]))
