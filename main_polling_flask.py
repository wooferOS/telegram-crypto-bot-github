import os
import json
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask
from telebot import TeleBot, types
from binance.client import Client
from daily_analysis import run_daily_analysis
from daily_analysis import run_daily_analysis, get_usdt_to_uah_rate
from flask import request, jsonify

load_dotenv(".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

bot = TeleBot(TELEGRAM_TOKEN)
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

app = Flask(__name__)

@app.route("/health")
def health():
    return "✅ OK", 200

budget = {"USDT": 100}

WHITELIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT",
    "LTCUSDT", "BCHUSDT", "ATOMUSDT", "NEARUSDT", "FILUSDT", "ICPUSDT",
    "ETCUSDT", "HBARUSDT", "VETUSDT", "RUNEUSDT", "INJUSDT", "OPUSDT",
    "ARBUSDT", "SUIUSDT", "STXUSDT", "TIAUSDT", "SEIUSDT", "1000PEPEUSDT"
]

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

def get_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Баланс", "📈 Звіт")
    kb.row("🕘 Історія", "✅ Підтвердити купівлю")
    kb.row("❌ Підтвердити продаж", "🔄 Оновити")
    kb.row("🚫 Скасувати")
    return kb

@bot.message_handler(commands=["start", "menu"])
def send_welcome(message):
    text = (
        "👋 Вітаю! Я *GPT-криптобот* для Binance.\n\n"
        "Використовуйте кнопки або команди:\n"
        "`/balance`, `/report`, `/confirm_buy`, `/confirm_sell`, `/set_budget`"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@bot.message_handler(commands=["id"])
def show_id(message):
    bot.reply_to(message, f"Ваш chat ID: `{message.chat.id}`", parse_mode="Markdown")

def send_balance(message):
    try:
        balances = client.get_account()["balances"]
        response = "📊 *Ваш поточний баланс:*\n\n"
        total_usdt = 0
        for asset in balances:
            amount = float(asset["free"])
            if amount < 0.01:
                continue
            symbol = asset["asset"]
            try:
                price = float(client.get_symbol_ticker(symbol=f"{symbol}USDT")["price"])
            except:
                continue
            value = amount * price
            total_usdt += value
            response += f"▫️ {symbol}: {amount:.4f} ≈ {value:.2f} USDT\n"
        response += f"\n💰 *Загальна вартість:* {total_usdt:.2f} USDT"
        prices = {item["symbol"]: float(item["price"]) for item in client.get_all_tickers()}
        rate_uah = get_usdt_to_uah_rate()
        total_usdt = 0
        response = "📊 *Ваш поточний баланс:*\n\n"
        for asset in balances:
            free = float(asset["free"])
            locked = float(asset["locked"])
            amount = free + locked
            if amount < 0.0001:
                continue
            symbol = asset["asset"]
            if symbol in ["BNB", "BUSD", "USDC"]:  # Додай або зміни список виключень
                continue
            if symbol == "USDT":
                value = amount
            else:
                price_key = f"{symbol}USDT"
                price = prices.get(price_key)
                if not price:
                    continue
                value = round(amount * price, 2)
            total_usdt += value
            response += f"▫️ {symbol}: {amount:.6f} ≈ {value:.2f} USDT\n"
        response += f"\n💰 *Загальна вартість:* {total_usdt:.2f} USDT ≈ {round(total_usdt * rate_uah)}₴"
        bot.send_message(message.chat.id, response, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка: {str(e)}")

def send_report(message):
    try:
        bot.send_message(message.chat.id, "⏳ Формується GPT-звіт, зачекайте...")
        report = run_daily_analysis()
        if report:
            bot.send_message(message.chat.id, report, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при створенні звіту:\n{e}")

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    try:
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
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Помилка: {str(e)}")

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
            bot.reply_to(message, "❗️ Приклад: `/set_budget 150`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

@bot.message_handler(func=lambda m: True)
def handle_buttons(message):
    text = message.text
    if text == "📊 Баланс":
        send_balance(message)
    elif text == "📈 Звіт":
        send_report(message)
    elif text == "✅ Підтвердити купівлю":
        bot.send_message(message.chat.id, "✋ Оберіть монету для купівлі...")
    elif text == "❌ Підтвердити продаж":
        bot.send_message(message.chat.id, "✋ Оберіть монету для продажу...")
    elif text == "🔄 Оновити":
        send_report(message)
    elif text == "🚫 Скасувати":
        bot.send_message(message.chat.id, "❌ Дію скасовано.")
    else:
        bot.send_message(message.chat.id, "⚠️ Невідома команда. Напишіть /help або скористайтеся кнопками.")
        
@bot.message_handler(commands=["zarobyty"])
def handle_zarobyty(message):
    try:
        result = run_daily_analysis()
        buy_list = result.get("buy", [])
        sell_list = result.get("sell", [])
        
        if not buy_list and not sell_list:
            bot.send_message(message.chat.id, "📉 На сьогодні немає активних рекомендацій для купівлі або продажу.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        for symbol in sell_list:
            markup.add(types.InlineKeyboardButton(f"Заробляємо: продати {symbol}", callback_data=f"confirmsell_{symbol}"))
        for symbol in buy_list:
            markup.add(types.InlineKeyboardButton(f"Заробляємо: купити {symbol}", callback_data=f"confirmbuy_{symbol}"))

        bot.send_message(
            message.chat.id,
            "💡 *Що рекомендує GPT сьогодні:*\n\nНатисніть кнопку для підтвердження дії.",
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при генерації /zarobyty:\n{str(e)}")

def run_polling():
    print("🤖 Telegram polling запущено...")
    bot.polling(none_stop=True)

def run_flask():
    print("🌐 Flask-сервер для /health запущено на порту 10000")
    app.run(host="0.0.0.0", port=10000)
@app.route("/daily", methods=["POST"])

def trigger_daily_analysis():
    try:
        run_daily_analysis()
        return jsonify({"status": "ok", "message": "Аналіз запущено"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    threading.Thread(target=run_polling).start()
    run_flask()
