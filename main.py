# 📦 main.py — Telegram GPT-бoт для аналітики Binance

import os
import json
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telebot import TeleBot, types
from binance.client import Client
from flask import Flask
from threading import Thread
from daily_analysis import generate_daily_report

# 🔐 Завантаження .env
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

# 🔑 Змінні середовища
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

# 🤖 Telegram та Binance клієнти
bot = TeleBot(TELEGRAM_TOKEN)
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

# 💰 Поточний бюджет (буде оновлюватись через /set_budget)
budget = {"USDT": 100}

# ✅ Список дозволених монет (для купівлі/продажу)
WHITELIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT",
    "LTCUSDT", "BCHUSDT", "ATOMUSDT", "NEARUSDT", "FILUSDT", "ICPUSDT",
    "ETCUSDT", "HBARUSDT", "VETUSDT", "RUNEUSDT", "INJUSDT", "OPUSDT",
    "ARBUSDT", "SUIUSDT", "STXUSDT", "TIAUSDT", "SEIUSDT", "1000PEPEUSDT"
]

# ✅ Завантаження попереднього сигналу
def load_signal():
    try:
        with open("signal.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_signal(signal):
    with open("signal.json", "w") as f:
        json.dump(signal, f)

signal = load_signal()
# 🧭 Головна клавіатура
def get_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Баланс", "📈 Звіт")
    kb.row("🕓 Історія", "✅ Підтвердити купівлю", "❌ Підтвердити продаж")
    kb.row("🔄 Оновити", "🚫 Скасувати")
    return kb
# 👋 Привітання
@bot.message_handler(commands=["start", "menu"])
def send_welcome(message):
    text = "👋 Вітаю! Я GPT-базований криптоасистент. Оберіть дію:"
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_keyboard())
# 📲 Основна клавіатура
def get_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Баланс", "📈 Звіт", "📜 Історія")
    kb.row("✅ Підтвердити купівлю", "❌ Підтвердити продаж")
    kb.row("🔄 Оновити", "❎ Скасувати")
    return kb
# 🚀 Обробник команди /start
@bot.message_handler(commands=["start", "menu"])
def send_welcome(message):
    text = (
        "🤖 *Telegram GPT-бот для Binance*\n\n"
        "Використовуйте кнопки нижче або наберіть команду вручну:\n"
        "- /balance — баланс гаманця\n"
        "- /report — GPT-звіт\n"
        "- /confirm_buy — підтвердити купівлю\n"
        "- /confirm_sell — підтвердити продаж\n"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_keyboard())
# 🧩 Основна клавіатура
def get_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Баланс", "🧠 Звіт")
    kb.row("🟢 Підтвердити купівлю", "🔴 Підтвердити продаж")
    kb.row("♻️ Оновити", "❌ Скасувати")
    return kb

# 🎯 Обробник для кнопок-клавіатури
@bot.message_handler(func=lambda m: True)
def handle_buttons(message):
    text = message.text
    if text == "📊 Баланс":
        send_balance(message)
    elif text == "🧠 Звіт":
        send_report(message)
    elif text == "🟢 Підтвердити купівлю":
        bot.send_message(message.chat.id, "✋ Оберіть монету для купівлі...")
    elif text == "🔴 Підтвердити продаж":
        bot.send_message(message.chat.id, "✋ Оберіть монету для продажу...")
    elif text == "♻️ Оновити":
        send_report(message)
    elif text == "❌ Скасувати":
        bot.send_message(message.chat.id, "❌ Дію скасовано.")
# 📊 Надсилання балансу (ручна команда або кнопка)
def send_balance(message):
    balances = get_binance_balance()
    if not balances:
        bot.send_message(message.chat.id, "❌ Не вдалося отримати баланс.")
        return

    response = "📊 *Ваш поточний баланс:*\n\n"
    total_usdt = 0
    for asset in balances:
        amount = float(asset['free'])
        if amount < 0.01:
            continue
        symbol = asset['asset']
        price = get_usdt_price(symbol)
        value = amount * price
        total_usdt += value
        response += f"▫️ {symbol}: {amount:.4f} ≈ {value:.2f} USDT\n"

    response += f"\n💰 *Загальна вартість:* {total_usdt:.2f} USDT"
    bot.send_message(message.chat.id, response, parse_mode="Markdown")
# 📈 Команда /report — GPT-аналітика ринку + баланс
@bot.message_handler(commands=['report', 'звіт'])
def handle_report(message):
    bot.send_message(message.chat.id, "⏳ Генерується GPT-звіт, зачекайте...")
    try:
        run_daily_analysis(telegram_mode=True)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка під час аналізу: {e}")
# 📥 Обробка підтвердження купівлі / продажу
@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    if call.message:
        if call.data.startswith("confirmbuy_"):
            pair = call.data.split("_")[1]
            bot.send_message(call.message.chat.id, f"✅ Ви підтвердили купівлю {pair}")
            signal["last_action"] = {
                "type": "buy",
                "pair": pair,
                "time": datetime.utcnow().isoformat()
            }
            save_signal(signal)

        elif call.data.startswith("confirmsell_"):
            pair = call.data.split("_")[1]
            bot.send_message(call.message.chat.id, f"✅ Ви підтвердили продаж {pair}")
            signal["last_action"] = {
                "type": "sell",
                "pair": pair,
                "time": datetime.utcnow().isoformat()
            }
            save_signal(signal)
# 📌 Команда /id — показати chat_id
@bot.message_handler(commands=["id"])
def show_id(message):
    bot.reply_to(message, f"Ваш chat ID: `{message.chat.id}`", parse_mode="Markdown")

# 💰 Команда /set_budget — встановлення бюджету
@bot.message_handler(commands=["set_budget"])
def set_budget(message):
    try:
        parts = message.text.strip().split()
        if len(parts) == 2:
            amount = float(parts[1])
            budget["USDT"] = amount
            with open("budget.json", "w") as f:
                json.dump(budget, f)
            bot.reply_to(message, f"✅ Бюджет оновлено: {amount} USDT")
        else:
            bot.reply_to(message, "❗️ Приклад використання: `/set_budget 100`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

# 📋 Команда /menu — показати клавіатуру
@bot.message_handler(commands=["menu"])
def show_menu(message):
    kb = get_main_keyboard()
    bot.send_message(message.chat.id, "📍 Меню команд:", reply_markup=kb)
# ✅ Обробка підтвердження купівлі/продажу
@bot.callback_query_handler(func=lambda call: call.data.startswith("confirmbuy_") or call.data.startswith("confirmsell_"))
def callback_inline(call):
    if call.data.startswith("confirmbuy_"):
        pair = call.data.split("_")[1]
        bot.send_message(call.message.chat.id, f"✅ Ви підтвердили купівлю {pair}")
        signal["last_action"] = {
            "type": "buy",
            "pair": pair,
            "time": datetime.utcnow().isoformat()
        }
        save_signal(signal)

    elif call.data.startswith("confirmsell_"):
        pair = call.data.split("_")[1]
        bot.send_message(call.message.chat.id, f"✅ Ви підтвердили продаж {pair}")
        signal["last_action"] = {
            "type": "sell",
            "pair": pair,
            "time": datetime.utcnow().isoformat()
        }
        save_signal(signal)

# ✅ Обробка помилок
@bot.message_handler(func=lambda message: True)
def fallback(message):
    bot.reply_to(message, "⚠️ Невідома команда. Напишіть /help або скористайтеся кнопками.")

# ✅ Обробка звіту (GPT-аналітика)
@bot.message_handler(commands=["report", "звіт"])
def send_report(message):
    try:
        gpt_report = run_daily_analysis()
        bot.send_message(message.chat.id, gpt_report, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при формуванні звіту:\n{e}")
# ✅ Завантажити сигнал з файлу
def load_signal():
    try:
        with open("signal.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# ✅ Зберегти сигнал у файл
def save_signal(signal):
    with open("signal.json", "w") as f:
        json.dump(signal, f)
# Binance client
client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# ✅ Завантажити попередній сигнал
signal = load_signal()
@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    if call.data.startswith("confirmbuy_"):
        pair = call.data.split("_")[1]
        bot.send_message(call.message.chat.id, f"✅ Ви підтвердили купівлю {pair}")
        signal["last_action"] = {
            "type": "buy",
            "pair": pair,
            "time": datetime.utcnow().isoformat()
        }
        save_signal(signal)

    elif call.data.startswith("confirmsell_"):
        pair = call.data.split("_")[1]
        bot.send_message(call.message.chat.id, f"✅ Ви підтвердили продаж {pair}")
        signal["last_action"] = {
            "type": "sell",
            "pair": pair,
            "time": datetime.utcnow().isoformat()
        }
        save_signal(signal)

if __name__ == "__main__":
    print("🚀 Бот запущено!")
    bot.polling(none_stop=True)

