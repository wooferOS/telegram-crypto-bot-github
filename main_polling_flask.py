import os
import json
import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
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

def send_daily_forecast():
    try:
        result = run_daily_analysis()
        report = result.get("report", "")
        if report:
            bot.send_message(ADMIN_CHAT_ID, report, parse_mode="Markdown")
            print("✅ Щоденний прогноз відправлено.")
        else:
            bot.send_message(ADMIN_CHAT_ID, "⚠️ Прогноз порожній.")
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"❌ Помилка щоденного прогнозу:\n{e}")

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
        order = client.create_oco_order(
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
def send_report(message):
    try:
        bot.send_message(message.chat.id, "⏳ Формується GPT-звіт, зачекайте...")
        result = run_daily_analysis()
        report = result.get("report", "")
        if report:
            bot.send_message(message.chat.id, report, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "⚠️ Звіт порожній.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при створенні звіту:\n{str(e)}")

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
        report_text = result.get("report", "")

        if not buy_list and not sell_list:
            bot.send_message(
                message.chat.id,
                "📉 На сьогодні немає активних рекомендацій для купівлі або продажу."
            )
            return

        # 🧠 Емоджі для токенів
        emoji_map = {
            "BTC": "₿", "ETH": "🌐", "BNB": "🔥", "SOL": "☀️", "XRP": "💧",
            "ADA": "🔷", "DOGE": "🐶", "AVAX": "🗻", "DOT": "🎯", "TRX": "💡",
            "LINK": "🔗", "MATIC": "🛡", "LTC": "🌕", "BCH": "🍀", "NEAR": "📡",
            "FIL": "📁", "ICP": "🧠", "ETC": "⚡", "HBAR": "🌀", "INJ": "💉",
            "VET": "✅", "RUNE": "⚓", "OP": "📈", "ARB": "🏹", "SUI": "💧",
            "STX": "📦", "TIA": "🪙", "SEI": "🌊", "ATOM": "🌌", "1000PEPE": "🐸"
        }

        def add_emoji(sym):
            for key in emoji_map:
                if sym.startswith(key):
                    return f"{emoji_map[key]} {sym}"
            return sym

        # 🧾 Формуємо текст
        summary = "💡 *GPT-прогноз на день:*\n\n"
        if sell_list:
            summary += "🔻 *Рекомендовано продати:*\n"
            summary += ", ".join(f"`{add_emoji(s)}`" for s in sell_list) + "\n\n"
        if buy_list:
            summary += "🟢 *Рекомендовано купити:*\n"
            summary += ", ".join(f"`{add_emoji(s)}`" for s in buy_list) + "\n\n"
        summary += "📥 Натисніть кнопку для підтвердження дії."

        # 🔘 Кнопки
        markup = types.InlineKeyboardMarkup(row_width=1)
        for symbol in sell_list:
            markup.add(types.InlineKeyboardButton(f"🔻 Продати {symbol}", callback_data=f"confirmsell_{symbol}"))
        for symbol in buy_list:
            markup.add(types.InlineKeyboardButton(f"🟢 Купити {symbol}", callback_data=f"confirmbuy_{symbol}"))

        # 📤 Відправка прогнозу
        bot.send_message(
            message.chat.id,
            summary,
            parse_mode="Markdown",
            reply_markup=markup
        )

        # 🧠 Додатково — повний GPT-звіт
        if report_text:
            bot.send_message(message.chat.id, report_text, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при генерації /zarobyty:\n{str(e)}")

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


def run_polling():
    print("🤖 Telegram polling запущено...")
    bot.polling(none_stop=True)
    
# 🕒 Планувальник щоденного прогнозу
scheduler = BackgroundScheduler()
scheduler.add_job(send_daily_forecast, trigger='cron', hour=9, minute=0)
scheduler.start()
print("⏰ APScheduler запущено — прогноз буде надсилатись щодня о 09:00")
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
