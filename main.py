# 📦 main.py — Telegram бот для GPT-аналітики Binance

import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from telebot import TeleBot
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from binance.client import Client
from flask import Flask
from threading import Thread
from daily_analysis import run_daily_analysis

# Завантаження .env
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)
# Ініціалізація змінних середовища
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

# Ініціалізація клієнтів
bot = TeleBot(TELEGRAM_TOKEN)
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

# Логування
logging.basicConfig(level=logging.INFO)
# 📱 Клавіатура
main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
main_keyboard.add(
    KeyboardButton("📊 Баланс"),
    KeyboardButton("📈 Звіт"),
    KeyboardButton("📜 Історія"),
)
main_keyboard.add(
    KeyboardButton("✅ Підтвердити купівлю"),
    KeyboardButton("❌ Підтвердити продаж")
)
main_keyboard.add(
    KeyboardButton("🔄 Оновити"),
    KeyboardButton("🚫 Скасувати")
)
# 🟢 Команди старту
@bot.message_handler(commands=["start", "menu", "help"])
def start_handler(message):
    bot.send_message(
        message.chat.id,
        "👋 Вітаю! Я GPT-аналітик крипторинку Binance.\n\nНатисніть кнопку нижче або оберіть команду:",
        reply_markup=main_keyboard
    )
# 📊 Баланс
@bot.message_handler(func=lambda m: m.text == "📊 Баланс")
def handle_balance(message):
    balances = client.get_account().get("balances", [])
    text = "📊 <b>Поточний баланс Binance:</b>\n\n"
    total_usdt = 0.0

    for asset in balances:
        free = float(asset["free"])
        locked = float(asset["locked"])
        total = free + locked
        if total > 0 and asset["asset"] != "USDT":
            symbol = f'{asset["asset"]}USDT'
            try:
                price = float(client.get_symbol_ticker(symbol=symbol)["price"])
                value = round(total * price, 2)
                total_usdt += value
                text += f'▫️ <b>{asset["asset"]}</b>: {round(total, 4)} ≈ {value} USDT\n'
            except:
                continue
        elif asset["asset"] == "USDT":
            total_usdt += total
            text += f'▫️ <b>USDT</b>: {round(total, 2)} USDT\n'

    text += f"\n<b>Загальна вартість:</b> {round(total_usdt, 2)} USDT"
    bot.send_message(message.chat.id, text, parse_mode="HTML")
# 📈 Звіт
@bot.message_handler(func=lambda m: m.text == "📈 Звіт")
def handle_report(message):
    msg = bot.send_message(message.chat.id, "📡 Зачекай, формую GPT-звіт...")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(generate_daily_report())
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=result, parse_mode=ParseMode.HTML)
    except Exception as e:
        error_text = f"❌ Помилка формування звіту: {str(e)}"
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=error_text)
        logging.error(error_text)
# 📊 Баланс
@bot.message_handler(func=lambda m: m.text == "📊 Баланс")
def handle_balance(message):
    try:
        balances = client.get_account()["balances"]
        text = "<b>💰 Поточний баланс:</b>\n\n"
        for asset in balances:
            free = float(asset["free"])
            locked = float(asset["locked"])
            total = free + locked
            if total > 0:
                text += f"{asset['asset']}: {total:.4f}\n"
        bot.send_message(message.chat.id, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка отримання балансу: {str(e)}")
        logging.error(f"BALANCE ERROR: {str(e)}")
# 📈 Звіт
@bot.message_handler(func=lambda m: m.text == "📈 Звіт")
def handle_report(message):
    try:
        bot.send_message(message.chat.id, "⏳ Генеруємо звіт...")
        asyncio.run(generate_daily_report())
        bot.send_message(message.chat.id, "✅ Звіт надіслано.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка генерації звіту: {str(e)}")
        logging.error(f"REPORT ERROR: {str(e)}")
# 🟢 Підтвердити купівлю
@bot.message_handler(func=lambda m: m.text == "🟢 Підтвердити купівлю")
def handle_confirm_buy(message):
    bot.send_message(message.chat.id, "✅ Підтвердження купівлі буде реалізовано окремою логікою.")

# 🔴 Підтвердити продаж
@bot.message_handler(func=lambda m: m.text == "🔴 Підтвердити продаж")
def handle_confirm_sell(message):
    bot.send_message(message.chat.id, "✅ Підтвердження продажу буде реалізовано окремою логікою.")

# ♻️ Оновити
@bot.message_handler(func=lambda m: m.text == "♻️ Оновити")
def handle_refresh(message):
    bot.send_message(message.chat.id, "🔄 Дані оновлюються...")
    asyncio.run(generate_daily_report())

# ❌ Скасувати
@bot.message_handler(func=lambda m: m.text == "❌ Скасувати")
def handle_cancel(message):
    bot.send_message(message.chat.id, "❎ Дію скасовано.")
# Обробка callback-кнопок (якщо використовуєш inline-кнопки)
@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call: CallbackQuery):
    try:
        if call.data.startswith("confirmbuy_"):
            pair = call.data.split("_")[1]
            bot.send_message(call.message.chat.id, f"✅ Ви підтвердили купівлю {pair}")
            # Тут буде логіка купівлі через Binance API

        elif call.data.startswith("confirmsell_"):
            pair = call.data.split("_")[1]
            bot.send_message(call.message.chat.id, f"✅ Ви підтвердили продаж {pair}")
            # Тут буде логіка продажу через Binance API

        else:
            bot.send_message(call.message.chat.id, "⚠️ Невідома дія.")
    except Exception as e:
        logging.error(f"❌ Callback помилка: {e}")
        bot.send_message(call.message.chat.id, "❌ Сталася помилка при обробці дії.")
# Flask app для healthcheck
app = Flask(__name__)

@app.route("/health", methods=["GET", "HEAD"])
def health_check():
    return "OK", 200

def run_flask():
    app.run(host="0.0.0.0", port=10000)

def run_bot():
    logging.info("🚀 Бот запущено!")
    bot.infinity_polling()
if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    run_bot()
