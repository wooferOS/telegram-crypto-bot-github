# summary_and_profit_logger.py
import os
import json
from datetime import datetime
from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from dotenv import load_dotenv

load_dotenv()

HISTORY_FILE = "history.json"
PROFIT_FILE = "profit_tracker.json"


def summary(update: Update, context: CallbackContext):
    if not os.path.exists(HISTORY_FILE):
        update.message.reply_text("📂 Історія операцій порожня.")
        return
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    buys = [d for d in data if d.get("side") == "BUY"]
    sells = [d for d in data if d.get("side") == "SELL"]

    total_buys = sum(d.get("qty", 0) * d.get("price", 0) for d in buys if "price" in d)
    total_sells = sum(d.get("qty", 0) * d.get("price", 0) for d in sells if "price" in d)

    summary_msg = f"📊 Підсумок портфелю:\n"
    summary_msg += f"💸 Куплено на: {round(total_buys, 2)} USDT\n"
    summary_msg += f"💰 Продано на: {round(total_sells, 2)} USDT\n"
    summary_msg += f"📈 Поточний прибуток: {round(total_sells - total_buys, 2)} USDT"
    update.message.reply_text(summary_msg)


def log_profit(trade):
    # trade: {symbol, side, qty, price}
    if not os.path.exists(PROFIT_FILE):
        profit_data = []
    else:
        with open(PROFIT_FILE, "r", encoding="utf-8") as f:
            profit_data = json.load(f)

    profit_data.append({
        "timestamp": datetime.now().isoformat(),
        **trade
    })

    with open(PROFIT_FILE, "w", encoding="utf-8") as f:
        json.dump(profit_data, f, indent=2, ensure_ascii=False)


def auto_logger(update: Update, context: CallbackContext):
    if not os.path.exists(PROFIT_FILE):
        update.message.reply_text("📂 Немає даних про прибуток.")
        return
    with open(PROFIT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    text = "🧾 Лог прибутку (останні 5):\n"
    for entry in data[-5:]:
        time = entry["timestamp"].split("T")[0]
        text += f"{time} — {entry['side']} {entry['symbol']} {entry['qty']} @ {entry['price']}\n"
    update.message.reply_text(text)


def add_handlers(app):
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("profit_log", auto_logger))
