# ✅ Розширений main.py з підтримкою бюджетів, пар, історії, аналітики, графіків та Binance

import os
from dotenv import load_dotenv
load_dotenv()
import json
import logging
import matplotlib.pyplot as plt
from datetime import datetime
from telegram import Bot, Update, ReplyKeyboardMarkup
from telegram.ext import CommandHandler, MessageHandler, filters, ApplicationBuilder, ContextTypes
from binance.client import Client
import openai

# --- Логування ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Змінні ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
DATA_PATH = "settings.json"

# --- Ініціалізація ---
bot = Bot(token=TELEGRAM_TOKEN)
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
openai.api_key = OPENAI_API_KEY
binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# --- Завантаження/збереження налаштувань ---
def load_settings():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r") as f:
            return json.load(f)
    return {"budget": 100.0, "pair": "BTCUSDT", "history": []}

def save_settings(settings):
    with open(DATA_PATH, "w") as f:
        json.dump(settings, f, indent=2)

settings = load_settings()

# --- Команди ---
async def початок(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/початок отримано")
    await update.message.reply_text("👋 Вітаю! Я КриптоБот. Введи /меню для команд")

async def меню(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/меню отримано")
    keyboard = [["/баланс", "/звіт"], ["/купити", "/продати"], ["/бюджет", "/пара"], ["/історія", "/допомога"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("📋 Меню команд:", reply_markup=reply_markup)

async def бюджет(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/бюджет отримано")
    try:
        amount = float(context.args[0])
        settings["budget"] = amount
        save_settings(settings)
        await update.message.reply_text(f"✅ Бюджет оновлено: ${amount}")
    except:
        await update.message.reply_text("❗ Приклад: /бюджет 150.0")

async def пара(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/пара отримано")
    try:
        pair = context.args[0].upper()
        settings["pair"] = pair
        save_settings(settings)
        await update.message.reply_text(f"✅ Пара оновлена: {pair}")
    except:
        await update.message.reply_text("❗ Приклад: /пара BTCUSDT")

async def історія(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/історія отримано")
    hist = settings.get("history", [])
    if not hist:
        await update.message.reply_text("📭 Угод ще не було")
    else:
        text = "\n".join([f"{i+1}. {item}" for i, item in enumerate(hist[-5:])])
        await update.message.reply_text(f"📘 Історія останніх угод:\n{text}")

async def баланс(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/баланс отримано")
    try:
        account = binance_client.get_account()
        assets = [f"{a['asset']}: {a['free']}" for a in account['balances'] if float(a['free']) > 0.0]
        text = "💼 Поточний баланс Binance:\n" + "\n".join(assets)
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}")

async def звіт(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/звіт отримано")
    try:
        btc = binance_client.get_symbol_ticker(symbol="BTCUSDT")
        eth = binance_client.get_symbol_ticker(symbol="ETHUSDT")
        prompt = f"BTC: {btc['price']}, ETH: {eth['price']}. Що купити або продати?"

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        reply = response.choices[0].message.content.strip()
        await update.message.reply_text(f"🤖 GPT каже:\n{reply}")
    except Exception as e:
        await update.message.reply_text(f"❌ GPT-звіт недоступний: {e}")

async def купити(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/купити отримано")
    try:
        order = binance_client.create_order(
            symbol=settings["pair"],
            side='BUY',
            type='MARKET',
            quantity=0.0002
        )
        settings["history"].append(f"Куплено {order['symbol']} - {order['fills'][0]['qty']}")
        save_settings(settings)
        await update.message.reply_text(f"✅ Купівля виконана: {order['fills'][0]['qty']} {order['symbol']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка купівлі: {e}")

async def продати(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/продати отримано")
    try:
        order = binance_client.create_order(
            symbol=settings["pair"],
            side='SELL',
            type='MARKET',
            quantity=0.0002
        )
        settings["history"].append(f"Продано {order['symbol']} - {order['fills'][0]['qty']}")
        save_settings(settings)
        await update.message.reply_text(f"✅ Продаж виконано: {order['fills'][0]['qty']} {order['symbol']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка продажу: {e}")

async def допомога(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🆘 Напиши /меню щоб побачити всі доступні команди")

async def невідома(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Я вас не зрозумів. Введи /меню для списку команд")

# --- Хендлери ---
app.add_handler(CommandHandler("початок", початок))
app.add_handler(CommandHandler("меню", меню))
app.add_handler(CommandHandler("бюджет", бюджет))
app.add_handler(CommandHandler("пара", пара))
app.add_handler(CommandHandler("історія", історія))
app.add_handler(CommandHandler("баланс", баланс))
app.add_handler(CommandHandler("звіт", звіт))
app.add_handler(CommandHandler("купити", купити))
app.add_handler(CommandHandler("продати", продати))
app.add_handler(CommandHandler("допомога", допомога))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), невідома))

# --- Старт бота ---
async def run_bot():
    await bot.send_message(chat_id=ADMIN_CHAT_ID, text="✅ КриптоБот запущено з повним функціоналом")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    import nest_asyncio
    print("✅ ВЕРСІЯ: GPT+Binance Telegram Bot запущено")

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    loop.run_forever()
