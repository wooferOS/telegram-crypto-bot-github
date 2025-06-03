# 📦 main.py — Telegram GPT-криптобот із Flask, APScheduler та GPT-аналітикою

import os
import json
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from telebot import TeleBot, types
from binance.client import Client
from apscheduler.schedulers.background import BackgroundScheduler
from daily_analysis import run_daily_analysis, get_usdt_to_uah_rate
from binance_api import get_current_portfolio
from daily_analysis import get_historical_data

# 🔐 Завантаження .env
load_dotenv(".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
print(f"🧪 TELEGRAM_TOKEN loaded: {TELEGRAM_TOKEN[:10]}")  # Діагностика

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

# 🤖 Telegram-бот і Binance API
bot = TeleBot(TELEGRAM_TOKEN)
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
# 🌐 Flask-сервер
app = Flask(__name__)

@app.route("/health")
def health():
    return "✅ OK", 200


# 💰 Бюджет за замовчуванням
budget = {"USDT": 100}

# 📋 Базовий whitelist активів
WHITELIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT",
    "LTCUSDT", "BCHUSDT", "ATOMUSDT", "NEARUSDT", "FILUSDT", "ICPUSDT",
    "ETCUSDT", "HBARUSDT", "VETUSDT", "RUNEUSDT", "INJUSDT", "OPUSDT",
    "ARBUSDT", "SUIUSDT", "STXUSDT", "TIAUSDT", "SEIUSDT", "1000PEPEUSDT"
]
# 🧠 Завантаження сигналів
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

# ⌨️ Основна клавіатура
def get_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Баланс", "📈 Звіт")
    kb.row("🕘 Історія", "✅ Підтвердити купівлю")
    kb.row("❌ Підтвердити продаж", "🔄 Оновити")
    kb.row("🚫 Скасувати")
    return kb

# 📬 Щоденне надсилання прогнозу
def send_daily_forecast():
    try:
        current = get_current_portfolio()
        historical = get_historical_data()
        analysis, total_pnl = run_daily_analysis(current, historical)

        if not analysis:
            bot.send_message(ADMIN_CHAT_ID, "⚠️ Прогноз порожній.")
            return

        usdt_to_uah = get_usdt_to_uah_rate()
        message_text = format_analysis_report(analysis, total_pnl, usdt_to_uah)
        bot.send_message(ADMIN_CHAT_ID, message_text, parse_mode="Markdown")
        print("✅ Щоденний прогноз відправлено.")
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"❌ Помилка щоденного прогнозу:\n{e}")

# 👋 Привітання
@bot.message_handler(commands=["start", "menu"])
def send_welcome(message):
    text = (
        "👋 Вітаю! Я *GPT-криптобот* для Binance.\n\n"
        "Використовуйте кнопки або команди:\n"
        "`/balance`, `/report`, `/confirm_buy`, `/confirm_sell`, `/set_budget`, `/zarobyty`, `/stats`"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@bot.message_handler(commands=["id"])
def show_id(message):
    bot.reply_to(message, f"Ваш chat ID: `{message.chat.id}`", parse_mode="Markdown")

# 💰 /set_budget — встановлення бюджету
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

# 📊 Баланс Binance
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
        bot.send_message(message.chat.id, response, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка: {str(e)}")

# 📈 GPT-звіт
def send_report(message):
    try:
        bot.send_message(message.chat.id, "⏳ Формується GPT-звіт, зачекайте...")
        current = get_current_portfolio()
        historical = get_historical_data()
        analysis, total_pnl = run_daily_analysis(current, historical)
        usdt_to_uah = get_usdt_to_uah_rate()
        report = format_analysis_report(analysis, total_pnl, usdt_to_uah)
        bot.send_message(message.chat.id, report, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при створенні звіту:\n{e}")

# ✅ Inline-підтвердження покупки/продажу + стоп-ордери
@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    try:
        if call.data.startswith("confirmbuy_") or call.data.startswith("confirmsell_"):
            parts = call.data.split("_", 1)
            if len(parts) != 2:
                bot.send_message(call.message.chat.id, "⚠️ Невірний формат команди.")
                return

            action, symbol = parts[0], parts[1]
            action_type = "buy" if action == "confirmbuy" else "sell"
            verb = "купівлю" if action_type == "buy" else "продаж"

            bot.send_message(call.message.chat.id, f"✅ Ви підтвердили {verb} {symbol}")

            # 🧠 Збереження історії
            timestamp = datetime.utcnow().isoformat()
            signal["last_action"] = {
                "type": action_type,
                "pair": symbol,
                "time": timestamp
            }
            history = signal.get("history", [])
            history.append({
                "type": action_type,
                "pair": symbol,
                "time": timestamp
            })
            signal["history"] = history
            save_signal(signal)

            # 🛡 Автоматичне встановлення стопів
            success = place_safety_orders(symbol, action_type)
            if success:
                bot.send_message(call.message.chat.id, f"🛡 Стоп-лос/тейк-профіт встановлено для {symbol}.")
            else:
                bot.send_message(call.message.chat.id, f"⚠️ Не вдалося встановити стопи для {symbol}.")
        else:
            bot.send_message(call.message.chat.id, "⚠️ Невідома дія.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Помилка обробки кнопки: {str(e)}")

def place_safety_orders(symbol: str, action_type: str):
    try:
        # Отримуємо ринкову ціну
        price_data = client.get_symbol_ticker(symbol=f"{symbol}USDT")
        current_price = float(price_data["price"])

        quantity = 10 / current_price  # 🔁 Тимчасово — $10 на одну угоду

        # Розрахунок цілей
        if action_type == "buy":
            tp_price = round(current_price * 1.06, 4)
            sl_price = round(current_price * 0.97, 4)
            side = "SELL"
        else:
            tp_price = round(current_price * 0.94, 4)
            sl_price = round(current_price * 1.03, 4)
            side = "BUY"

        # Створення OCO ордера
        client.create_oco_order(
            symbol=f"{symbol}USDT",
            side=side,
            quantity=round(quantity, 3),
            price=str(tp_price),
            stopPrice=str(sl_price),
            stopLimitPrice=str(sl_price),
            stopLimitTimeInForce='GTC'
        )

        print(f"✅ Стопи для {symbol} встановлені.")
        return True
    except Exception as e:
        print(f"❌ Помилка встановлення стопів для {symbol}: {e}")
        return False
        
@bot.message_handler(commands=["zarobyty"])
def handle_zarobyty(message):
    print("🔥 /zarobyty отримано")

    try:
        current = get_current_portfolio()
        historical = get_historical_data()
        analysis, total_pnl = run_daily_analysis(current, historical)

        if not analysis:
            bot.send_message(
                message.chat.id,
                "📉 На сьогодні немає активних змін понад ±1%."
            )
            return

        usdt_to_uah = get_usdt_to_uah_rate()
        message_text = format_analysis_report(analysis, total_pnl, usdt_to_uah)

        bot.send_message(
            message.chat.id,
            message_text,
            parse_mode="Markdown"
        )

    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"❌ Помилка при генерації /zarobyty:\n{str(e)}"
        )


@bot.message_handler(commands=["stats"])
def handle_stats(message):
    try:
        history = signal.get("history", [])
        if not history:
            bot.send_message(message.chat.id, "ℹ️ Історія порожня. Немає даних для обчислення.")
            return

        stats = {"buy": {}, "sell": {}}
        for action in history:
            symbol = action.get("pair")
            action_type = action.get("type")
            time_str = action.get("time")
            if not symbol or not time_str:
                continue
            stats[action_type].setdefault(symbol, 0)
            stats[action_type][symbol] += 1

        text = "*📊 Статистика дій:*\n\n"
        if stats["buy"]:
            text += "🟢 *Куплено:*\n"
            for sym, count in stats["buy"].items():
                text += f"• {sym}: `{count}` разів\n"
        if stats["sell"]:
            text += "\n🔻 *Продано:*\n"
            for sym, count in stats["sell"].items():
                text += f"• {sym}: `{count}` разів\n"

        total = sum(stats["buy"].values()) + sum(stats["sell"].values())
        text += f"\n📈 *Загалом операцій:* `{total}`"

        bot.send_message(message.chat.id, text, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка у /stats: {e}")
# 🎯 Обробка кнопок інтерфейсу
@bot.message_handler(func=lambda m: True)
def handle_buttons(message):
    text = message.text
    if text == "📊 Баланс":
        send_balance(message)
    elif text == "📈 Звіт":
        send_report(message)
    elif text == "🕘 Історія":
        handle_stats(message)
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


# 🚀 Запуск Telegram polling
def run_polling():
    print("🤖 Telegram polling запущено...")
    bot.polling(none_stop=True)

# 🌐 Запуск Flask-сервера
def run_flask():
    print("🌐 Flask-сервер для /health запущено на порту 10100")
    app.run(host="0.0.0.0", port=10100)

# 🛠 Ручний запуск аналізу (debug endpoint)
@app.route("/run_analysis")
def trigger_daily_analysis():
    try:
        current = get_current_portfolio()
        historical = get_historical_data()

        print("🟡 BEFORE run_daily_analysis")

        result = run_daily_analysis(current, historical)

        print(f"🟢 AFTER run_daily_analysis: {result}")

        analysis, total_pnl = result
        usdt_to_uah = get_usdt_to_uah_rate()
        message_text = format_analysis_report(analysis, total_pnl, usdt_to_uah)
        return jsonify({"status": "ok", "message": message_text}), 200

    except Exception as e:
        print(f"❌ EXCEPTION in /run_analysis: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500



        
if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_daily_forecast, trigger="cron", hour=9, minute=0)
    scheduler.start()
    print("⏰ APScheduler запущено — прогноз буде надсилатись щодня о 09:00")

    threading.Thread(target=run_polling).start()
    run_flask()

    
# 🧪 Обробка тестової inline-кнопки
@bot.callback_query_handler(func=lambda call: call.data == "test_callback")
def handle_test_callback(call):
    bot.answer_callback_query(call.id, "✅ Кнопка спрацювала!")
    bot.send_message(call.message.chat.id, "🧪 Ви натиснули кнопку.")

# ✅ Діагностичне логування
print("📦 Бот завантажено успішно.")

# 🔢 Округлення кількості токенів до 3 знаків
def round_quantity(amount: float) -> float:
    return round(amount, 3)

# 🧠 Безпечне оновлення історії (на випадок зовнішнього використання)
def append_to_history(entry: dict):
    history = signal.get("history", [])
    history.append(entry)
    signal["history"] = history
    save_signal(signal)

# 🔄 Функція для отримання курсу USDT → UAH (може бути використана у /balance або майбутніх звітах)
# Ця функція імпортується з daily_analysis: get_usdt_to_uah_rate()

# 📂 JSON-файли, які використовуються:
# - signal.json → історія дій та остання дія
# - budget.json → встановлений бюджет користувача
# - balance_snapshot.json → збереження стану портфеля
# 🧹 Заміна legacy:
# Уся логіка з `main_polling_flask.py` перенесена до цього `main.py`.
# Тепер цей файл підтримує:
# - Telegram polling
# - Flask healthcheck
# - /zarobyty + /stats
# - Автоматичне надсилання прогнозу через APScheduler
# - OCO стоп-ордера
# - Зберігання сигналів та історії

# ✅ Рекомендовано видалити legacy-файл:
# ➤ `main_polling_flask.py`

# Виконати у терміналі:
# rm main_polling_flask.py
# ✅ Підсумок:
# Цей `main.py` тепер єдина точка входу для Telegram-криптобота.
# Він містить:
# - Telegram-бот із усіма командами
# - Flask-сервер для healthcheck та ручного запуску аналізу
# - APScheduler для щоденного прогнозу
# - Повна інтеграція з Binance + GPT

# 🚀 Запуск через systemd:
# Файл: /etc/systemd/system/crypto-bot.service

# [Unit]
# Description=Telegram GPT Crypto Bot
# After=network.target

# [Service]
# WorkingDirectory=/root/telegram-crypto-bot-github
# ExecStart=/usr/bin/python3 main.py
# Restart=always
# EnvironmentFile=/root/telegram-crypto-bot-github/.env

# [Install]
# WantedBy=multi-user.target

# Потім:
# sudo systemctl daemon-reload
# sudo systemctl restart crypto-bot
# sudo systemctl status crypto-bot
