import os
import json
import csv
import datetime
from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from dotenv import load_dotenv

load_dotenv()

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
HISTORY_FILE = "history.json"
SNAPSHOT_DIR = "snapshots"
RECOMMEND_FILE = "recommendations.json"

def forecast(update: Update, context: CallbackContext):
    message = "📈 Прогноз на 1–3 дні вперед (GPT-імітація):\n"
    message += "SUI: можливе зростання до +5.4%\n"
    message += "PEPE: низхідний тренд, ймовірне падіння -3.2%\n"
    message += "TON: консолідація, нейтральна позиція"
    update.message.reply_text(message)

def history_export(update: Update, context: CallbackContext):
    if not os.path.exists(HISTORY_FILE):
        update.message.reply_text("Історія угод відсутня.")
        return
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    csv_path = "history_export.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    update.message.reply_document(open(csv_path, "rb"), filename="history_export.csv")

def auto_trade(update: Update, context: CallbackContext):
    args = context.args
    if not args or args[0] not in ["on", "off"]:
        update.message.reply_text("❗ Приклад: /auto_trade on або /auto_trade off")
        return
    status = args[0]
    with open("auto_trade_status.json", "w") as f:
        json.dump({"auto_trade": status}, f)
    update.message.reply_text(f"🔁 Автоторгівля: {status.upper()}")

def risk_mode(update: Update, context: CallbackContext):
    args = context.args
    if not args or args[0] not in ["low", "high"]:
        update.message.reply_text("❗ Приклад: /risk_mode low або /risk_mode high")
        return
    mode = args[0]
    with open("risk_mode.json", "w") as f:
        json.dump({"mode": mode}, f)
    update.message.reply_text(f"⚠️ Режим ризику встановлено: {mode.upper()}")

def balance_snapshot(update: Update, context: CallbackContext):
    from binance.client import Client
    client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"))
    account = client.get_account()
    balances = {
        asset['asset']: float(asset['free'])
        for asset in account['balances']
        if float(asset['free']) > 0
    }
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    path = os.path.join(SNAPSHOT_DIR, f"snapshot_{now}.json")
    with open(path, "w") as f:
        json.dump(balances, f, indent=2)
    update.message.reply_text(f"📦 Баланс збережено: {path}")

def add_handlers(app):
    app.add_handler(CommandHandler("forecast", forecast))
    app.add_handler(CommandHandler("history_export", history_export))
    app.add_handler(CommandHandler("auto_trade", auto_trade))
    app.add_handler(CommandHandler("risk_mode", risk_mode))
    app.add_handler(CommandHandler("balance_snapshot", balance_snapshot))
