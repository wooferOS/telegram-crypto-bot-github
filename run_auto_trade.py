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

setup_logging()
logger = logging.getLogger(__name__)
logger.info("🚀 run_auto_trade.py запущено")

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

refresh_valid_pairs()

MIN_AUTO_TRADE_INTERVAL = 3600
AUTO_INTERVAL = max(TRADE_LOOP_INTERVAL, MIN_AUTO_TRADE_INTERVAL)
LAST_RUN_FILE = ".last_run.json"

def _time_since_last_run() -> float:
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
    try:
        with open(LAST_RUN_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time()}, f)
    except OSError:
        pass

def is_market_window_active():
    utc_hour = datetime.utcnow().hour
    return utc_hour in {2, 3, 13, 14}  # Китай (UTC+8) 10–11, США (UTC-4/5) 09–10

if __name__ == "__main__":
    if not is_market_window_active():
        logger.info("[dev] 💤 Ринок неактивний — трейд-цикл пропущено")
        raise SystemExit

    gpt_forecast = load_gpt_filters()
    gpt_filters = {
        "do_not_buy": gpt_forecast.get("do_not_buy", []),
        "recommend_buy": gpt_forecast.get("recommend_buy", []),
    }

    if not os.path.exists("predictions.json"):
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
    usdt_balance = get_binance_balances().get("USDT", 0)

    if elapsed >= AUTO_INTERVAL or sold_before or usdt_balance > 1:
        if elapsed < AUTO_INTERVAL and sold_before:
            logger.info("[dev] ⏱️ Запуск поза інтервалом через продаж активів")

        MAX_ATTEMPTS = 5
        attempt = 0
        summary = {"sold": [], "bought": []}
        if sold_before:
            summary["sold"].extend(sold_before)

        while attempt < MAX_ATTEMPTS:
            cycle_result = asyncio.run(main(int(ADMIN_CHAT_ID)))
            summary["sold"].extend(cycle_result.get("sold", []))
            summary["bought"].extend(cycle_result.get("bought", []))
            logger.info(f"[dev] Спроба {attempt + 1}: продано: {summary['sold']}, куплено: {summary['bought']}")
            if summary["sold"] or summary["bought"]:
                break
            attempt += 1
            logger.info(f"[dev] ⏳ Спроба {attempt}: жодної угоди. Повторюємо...")

        _store_run_time()

        if summary["sold"] or summary["bought"]:
            lines = ["[dev] 🧾 Звіт:"]
            if summary["sold"]:
                lines.append("\n🔁 Продано:")
                lines.extend(summary["sold"])
            if summary["bought"]:
                lines.append("\n📈 Куплено:")
                lines.extend(summary["bought"])
            lines.append(f"\n💰 Баланс до: {cycle_result.get('before', 0):.2f} USDT")
            lines.append(f"💰 Баланс після: {cycle_result.get('after', 0):.2f} USDT")
            lines.append("\n✅ Завершено успішно.")
            asyncio.run(send_messages(int(CHAT_ID), ["\n".join(lines)]))
        else:
            logger.warning("[dev] ❌ Після 5 спроб не вдалося виконати жодної угоди")
            logger.info("[dev] ⚠️ Причина: ймовірно всі токени відфільтровано або заблоковано (min_notional / lot_size / баланс)")
            lines = [
                "[dev] ⚠️ Усі 5 спроб завершились без дій.",
                "Можливі причини:",
                "- усі токени відфільтровано (score = 0 або low prob_up)",
                "- недостатній баланс для покупки",
                "- Binance обмеження (min_notional / lot_size)",
                "\n🕒 Цикл завершено без угод."
            ]
            asyncio.run(send_messages(int(CHAT_ID), ["\n".join(lines)]))
    else:
        minutes = int(elapsed / 60)
        msg = f"Автотрейд-цикл не запущено — останній запуск був {minutes} хвилин тому."
        asyncio.run(send_messages(int(CHAT_ID), [msg]))
