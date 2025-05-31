# 📦 main.py — Telegram бот для GPT-аналітики Binance

import logging
import os
import json
from dotenv import load_dotenv
from telebot import TeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from binance.client import Client
from datetime import datetime
from flask import Flask
from threading import Thread
from daily_analysis import generate_daily_report
import asyncio

# Завантаження змінних з .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

bot = TeleBot(TELEGRAM_TOKEN)
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
# 📲 Клавіатура для головного меню
def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📊 Баланс"),
        KeyboardButton("📈 Звіт"),
        KeyboardButton("📜 Історія"),
        KeyboardButton("✅ Підтвердити купівлю"),
        KeyboardButton("❌ Підтвердити продаж"),
        KeyboardButton("🔄 Оновити"),
        KeyboardButton("🚫 Скасувати")
    )
    return keyboard

# 🎉 Привітальне повідомлення
@bot.message_handler(commands=["start"])
def send_welcome(message):
    text = "🤖 *Вітаю у Telegram Crypto Bot!* Обери команду з меню."
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_keyboard())
# 📊 Показати баланс Binance
def get_binance_balance():
    try:
        account_info = client.get_account()
        balances = account_info["balances"]
        filtered = [b for b in balances if float(b["free"]) > 0 or float(b["locked"]) > 0]
        result = []
        for b in filtered:
            asset = b["asset"]
            free = float(b["free"])
            locked = float(b["locked"])
            total = free + locked
            result.append(f"{asset}: {total:.4f}")
        return "\n".join(result)
    except Exception as e:
        return f"❌ Помилка отримання балансу: {e}"

# Обробка кнопки 📊 Баланс
@bot.message_handler(func=lambda msg: msg.text == "📊 Баланс")
def handle_balance(msg):
    bot.send_message(msg.chat.id, "📊 Ваш баланс:\n" + get_binance_balance())
# 📋 Головна клавіатура
def get_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Баланс", "📈 Звіт")
    kb.row("🕘 Історія", "♻️ Оновити")
    kb.row("✅ Підтвердити купівлю", "✅ Підтвердити продаж")
    kb.row("❌ Скасувати")
    return kb

# Обробка команди /menu або кнопки "📋 Меню"
@bot.message_handler(commands=["menu"])
def show_menu(message):
    bot.send_message(message.chat.id, "📋 Обери дію:", reply_markup=get_main_keyboard())
# 🧾 Команда /balance або кнопка "📊 Баланс"
@bot.message_handler(commands=["balance"])
@bot.message_handler(func=lambda message: message.text == "📊 Баланс")
def send_balance(message):
    try:
        account_info = client.get_account()
        balances = account_info["balances"]
        text = "*💰 Баланс акаунта Binance:*\n\n"
        total = 0.0
        for b in balances:
            asset = b["asset"]
            free = float(b["free"])
            if free > 0:
                if asset == "USDT":
                    total += free
                text += f"• {asset}: `{free}`\n"
        text += f"\n*Загалом (USDT еквівалент):* `{round(total, 2)} USDT`"
        bot.send_message(message.chat.id, text, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка отримання балансу: {e}")

# 📈 Команда /report або кнопка "📈 Звіт"
@bot.message_handler(commands=["report"])
@bot.message_handler(func=lambda message: message.text == "📈 Звіт")
def send_report(message):
    try:
        bot.send_message(message.chat.id, "📡 Формую аналітичний звіт...")

        result = run_daily_analysis()
        bot.send_message(message.chat.id, result, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Не вдалося сформувати звіт: {e}")
# ✅ Обробка підтвердження купівлі
@bot.message_handler(commands=["confirmbuy"])
@bot.message_handler(func=lambda message: message.text == "✅ Підтвердити купівлю")
def confirm_buy(message):
    try:
        data = load_signal("buy")
        if not data:
            bot.send_message(message.chat.id, "ℹ️ Немає сигналу для купівлі.")
            return
        coin = data["symbol"]
        quantity = float(data["quantity"])
        price = float(data["price"])

        order = client.order_market_buy(symbol=f"{coin}USDT", quantity=round(quantity, 6))
        bot.send_message(message.chat.id, f"✅ Куплено {quantity} {coin} за ринковою ціною.")

        save_trade_history([{
            "symbol": coin,
            "action": "BUY",
            "quantity": quantity,
            "time": datetime.now().isoformat()
        }], action="BUY")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при купівлі: {e}")

# ✅ Обробка підтвердження продажу
@bot.message_handler(commands=["confirmsell"])
@bot.message_handler(func=lambda message: message.text == "✅ Підтвердити продаж")
def confirm_sell(message):
    try:
        data = load_signal("sell")
        if not data:
            bot.send_message(message.chat.id, "ℹ️ Немає сигналу для продажу.")
            return
        coin = data["symbol"]
        quantity = float(data["quantity"])
        price = float(data["price"])

        stop_price = round(price * 0.97, 4)
        limit_price = round(price * 1.05, 4)

        client.create_order(
            symbol=f"{coin}USDT",
            side="SELL",
            type="OCO",
            quantity=round(quantity, 6),
            price=str(limit_price),
            stopPrice=str(stop_price),
            stopLimitPrice=str(stop_price),
            stopLimitTimeInForce='GTC'
        )

        bot.send_message(message.chat.id, f"💚Stop-loss: {stop_price} | Take-profit: {limit_price} для {coin} встановлено.")
        bot.send_message(message.chat.id, f"✅Продано {quantity} {coin}.")

        save_trade_history([{
            "symbol": coin,
            "action": "SELL",
            "quantity": quantity,
            "time": datetime.now().isoformat()
        }], action="SELL")

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Не вдалося виконати операцію: {e}")
# ✅ Команда ручної купівлі
@bot.message_handler(commands=["buy"])
def handle_buy(message):
    try:
        args = message.text.split()
        if len(args) != 3:
            bot.send_message(message.chat.id, "❗ Формат: /buy BTC 0.01")
            return
        coin = args[1].upper()
        quantity = float(args[2])
        price = float(client.get_symbol_ticker(symbol=f"{coin}USDT")["price"])

        save_signal("buy", {
            "symbol": coin,
            "quantity": quantity,
            "price": price
        })
        bot.send_message(message.chat.id, f"📥 Сигнал купівлі {quantity} {coin} збережено.\nНатисни *✅ Підтвердити купівлю*", parse_mode="Markdown")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка: {e}")

# ✅ Команда ручного продажу
@bot.message_handler(commands=["sell"])
def handle_sell(message):
    try:
        args = message.text.split()
        if len(args) != 3:
            bot.send_message(message.chat.id, "❗ Формат: /sell BTC 0.01")
            return
        coin = args[1].upper()
        quantity = float(args[2])
        price = float(client.get_symbol_ticker(symbol=f"{coin}USDT")["price"])

        save_signal("sell", {
            "symbol": coin,
            "quantity": quantity,
            "price": price
        })
        bot.send_message(message.chat.id, f"📤 Сигнал продажу {quantity} {coin} збережено.\nНатисни *✅ Підтвердити продаж*", parse_mode="Markdown")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка: {e}")
# ✅ Підтвердження купівлі
@bot.message_handler(commands=["confirmbuy"])
def confirm_buy(message):
    try:
        with open("signals.json", "r") as f:
            data = json.load(f)
        buy = data.get("buy", {})
        coin = buy["symbol"]
        quantity = float(buy["quantity"])
        price = float(client.get_symbol_ticker(symbol=f"{coin}USDT")["price"])

        client.order_market_buy(
            symbol=f"{coin}USDT",
            quantity=quantity
        )
        bot.send_message(message.chat.id, f"✅ Куплено {quantity} {coin} за ціною ~{price}")

        save_trade_history([{
            "symbol": coin,
            "action": "BUY",
            "quantity": quantity,
            "time": datetime.now().isoformat()
        }], action="BUY")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при купівлі: {e}")

# ✅ Підтвердження продажу з Stop-Loss / Take-Profit
@bot.message_handler(commands=["confirmsell"])
def confirm_sell(message):
    try:
        with open("signals.json", "r") as f:
            data = json.load(f)
        sell = data.get("sell", {})
        coin = sell["symbol"]
        quantity = float(sell["quantity"])
        price = float(client.get_symbol_ticker(symbol=f"{coin}USDT")["price"])

        stop_price = round(price * 0.97, 4)      # -3%
        limit_price = round(price * 1.05, 4)     # +5%

        client.create_order(
            symbol=f"{coin}USDT",
            side="SELL",
            type="OCO",
            quantity=round(quantity, 6),
            price=str(limit_price),
            stopPrice=str(stop_price),
            stopLimitPrice=str(stop_price),
            stopLimitTimeInForce='GTC'
        )

        bot.send_message(message.chat.id, f"💚Stop-loss: {stop_price} | Take-profit: {limit_price} для {coin} встановлено.")
        bot.send_message(message.chat.id, f"✅Продано {quantity} {coin}.")

        save_trade_history([{
            "symbol": coin,
            "action": "SELL",
            "quantity": quantity,
            "time": datetime.now().isoformat()
        }], action="SELL")

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Не вдалося виконати операцію: {e}")
# 💰 Установка бюджету
@bot.message_handler(commands=["set_budget"])
def set_budget(message):
    msg = bot.send_message(message.chat.id, "📝 Введи бюджет у USDT:")
    bot.register_next_step_handler(msg, save_budget)

def save_budget(message):
    try:
        new_budget = float(message.text)
        with open("budget.json", "w") as f:
            json.dump({"budget": new_budget}, f)
        bot.reply_to(message, f"✅ Новий бюджет: *{new_budget}* USDT", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

# /menu — показати клавіатуру
@bot.message_handler(commands=["menu"])
def show_menu(message):
    bot.send_message(message.chat.id, "📋 Обери дію:", reply_markup=get_main_keyboard())

# 🗃️ Збереження історії угод
def save_trade_history(entries, action):
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    for entry in entries:
        entry["action"] = action
        entry["date"] = today
    try:
        history_file = "trade_history.json"
        if os.path.exists(history_file):
            with open(history_file, "r") as f:
                history = json.load(f)
        else:
            history = []
        history.extend(entries)
        with open(history_file, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print("❌ Помилка при збереженні історії:", e)
# Healthcheck Flask app
health_app = Flask(__name__)

@health_app.route("/health")
def health():
    return "OK", 200

def run_flask():
    health_app.run(host="0.0.0.0", port=10000)

# Запуск Flask у окремому потоці
flask_thread = Thread(target=run_flask)
flask_thread.start()

# ✅ Запуск Telegram-бота
if __name__ == "__main__":
    print("🚀 Бот запущено!")
    bot.polling(none_stop=True)
