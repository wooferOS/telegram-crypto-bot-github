# main.py — Telegram криптобот з GPT і Binance

import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)
from binance.client import Client
from openai import OpenAI

# --- Логування ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Змінні середовища ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
DATA_PATH = "settings.json"
NOTIFY_FILE = ".notified"

# --- Клієнти ---
client = OpenAI(api_key=OPENAI_API_KEY)
binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# --- Налаштування ---
def load_settings():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r") as f:
            return json.load(f)
    return {"budget": 100.0, "pair": "BTCUSDT", "history": [], "autotrade": False, "stop_loss": 5.0}

def save_settings(settings):
    with open(DATA_PATH, "w") as f:
        json.dump(settings, f, indent=2)

settings = load_settings()

# --- Команди ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Вітаю! Я Криптобот. Введи /menu для команд")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["/status", "/report"], ["/buy", "/sell"], ["/set_budget", "/set_pair"], ["/history", "/help"]]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("📋 Меню команд:", reply_markup=markup)

async def set_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(context.args[0])
        settings["budget"] = amount
        save_settings(settings)
        await update.message.reply_text(f"✅ Бюджет оновлено: ${amount}")
    except Exception:
        await update.message.reply_text("❗ Приклад: /set_budget 150.0")

async def set_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pair = context.args[0].upper()
        settings["pair"] = pair
        save_settings(settings)
        await update.message.reply_text(f"✅ Пара оновлена: {pair}")
    except:
        await update.message.reply_text("❗ Приклад: /set_pair BTCUSDT")

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hist = settings.get("history", [])
    if not hist:
        await update.message.reply_text("📍 Угод ще не було")
    else:
        text = "\n".join([f"{i+1}. {item}" for i, item in enumerate(hist[-5:])])
        await update.message.reply_text(f"📘 Історія останніх угод:\n{text}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        account = binance_client.get_account()
        assets = [f"{a['asset']}: {a['free']}" for a in account['balances'] if float(a['free']) > 0.0]
        await update.message.reply_text("💼 Поточний баланс Binance:\n" + "\n".join(assets))
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        btc = binance_client.get_symbol_ticker(symbol="BTCUSDT")
        eth = binance_client.get_symbol_ticker(symbol="ETHUSDT")
        prompt = f"BTC: {btc['price']}, ETH: {eth['price']}. Що купити або продати?"
        chat_response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        reply = chat_response.choices[0].message.content.strip()
        await update.message.reply_text(f"🧐 GPT каже:\n{reply}")
    except Exception as e:
        await update.message.reply_text(f"❌ GPT-звіт недоступний: {e}")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        order = binance_client.create_order(
            symbol=settings["pair"],
            side='BUY',
            type='MARKET',
            quantity=0.0002
        )
        settings["history"].append(f"Buy {order['symbol']} - {order['fills'][0]['qty']}")
        save_settings(settings)
        await update.message.reply_text(f"✅ Купівля виконана: {order['fills'][0]['qty']} {order['symbol']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка купівлі: {e}")

async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        order = binance_client.create_order(
            symbol=settings["pair"],
            side='SELL',
            type='MARKET',
            quantity=0.0002
        )
        settings["history"].append(f"Sell {order['symbol']} - {order['fills'][0]['qty']}")
        save_settings(settings)
        await update.message.reply_text(f"✅ Продаж виконано: {order['fills'][0]['qty']} {order['symbol']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка продажу: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
<b>📘 Довідка по командам:</b>
/start – запуск бота
/menu – кнопкове меню
/set_pair BTCUSDT – встановити торгову пару
/set_budget 100 – бюджет на купівлю
/status – баланс Binance
/report – GPT рекомендації
/buy – купити
/sell – продати
/history – останні угоди
/help – список команд
"""
    await update.message.reply_text(help_text, parse_mode="HTML")

async def notify_once_async(app):
    if not os.path.exists(NOTIFY_FILE):
        await app.bot.send_message(chat_id=ADMIN_CHAT_ID, text="✅ Crypto Bot запущено з polling")
        with open(NOTIFY_FILE, "w") as f:
            f.write(str(datetime.now()))

# --- Запуск ---
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("set_budget", set_budget))
    app.add_handler(CommandHandler("set_pair", set_pair))
    app.add_handler(CommandHandler("history", show_history))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("help", help_command))

    try:
        await notify_once_async(app)
    except Exception as e:
        logging.error(f"❌ Notify error: {e}")

    logging.info("🤖 Бот запущено через polling")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.get_event_loop().run_until_complete(main())



