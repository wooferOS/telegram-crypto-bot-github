# 📦 main.py — Telegram бот для криптоасистента з підтвердженнями та аналітикою

# ✅ ЧАСТИНА 1: Імпорти, .env, ініціалізація bot та Binance client
import os
import json
import datetime
from dotenv import load_dotenv
from telebot import TeleBot
from telebot.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from binance.client import Client
from daily_analysis import save_trade_history, generate_daily_report

# 🧪 Завантаження .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

bot = TeleBot(TELEGRAM_TOKEN)
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

# 📱 Меню кнопок
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        ["\U0001F4B0 Баланс", "\U0001F4CA Звіт", "\U0001F4D8 Історія"],
        ["\u2705 Підтвердити купівлю", "\u2705 Підтвердити продаж"],
        ["\U0001F504 Оновити", "\U0001F6D1 Скасувати"]
    ],
    resize_keyboard=True
)

# ✅ ЧАСТИНА 2: Кнопки: Баланс, Історія, Звіт, Оновити, Скасувати
@bot.message_handler(func=lambda message: message.text == "\U0001F4B0 Баланс")
def handle_balance(message):
    try:
        account_info = client.get_account()
        balances = [b for b in account_info["balances"] if float(b["free"]) > 0 or float(b["locked"]) > 0]

        text = "\U0001F4BC *Твій баланс:*\n"
        for b in balances:
            total = float(b["free"]) + float(b["locked"])
            text += f"- {b['asset']}: {total}\n"

        bot.send_message(message.chat.id, text, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"\u274C Помилка при отриманні балансу: {str(e)}")

@bot.message_handler(func=lambda message: message.text == "\U0001F4D8 Історія")
def handle_history_button(message):
    handle_history(message)

@bot.message_handler(func=lambda message: message.text == "\U0001F4CA Звіт")
def handle_report_button(message):
    report_handler(message)

@bot.message_handler(func=lambda message: message.text == "\U0001F504 Оновити")
def handle_refresh(message):
    bot.send_message(message.chat.id, "\U0001F504 Дані оновлено (реалізація триває)")

@bot.message_handler(func=lambda message: message.text == "\U0001F6D1 Скасувати")
def handle_cancel(message):
    bot.send_message(message.chat.id, "\u274C Операцію скасовано")
# 📘 Історія — кнопка
@bot.message_handler(func=lambda message: message.text == "📘 Історія")
def handle_history_button(message):
    handle_history(message)

# 📊 Звіт — кнопка
@bot.message_handler(func=lambda message: message.text == "📊 Звіт")
def handle_report_button(message):
    report_handler(message)

# 🔄 Оновити — демо
@bot.message_handler(func=lambda message: message.text == "🔄 Оновити")
def handle_refresh(message):
    bot.send_message(message.chat.id, "🔄 Дані оновлено (реалізація триває)")

# 🛑 Скасувати — демо
@bot.message_handler(func=lambda message: message.text == "🛑 Скасувати")
def handle_cancel(message):
    bot.send_message(message.chat.id, "❌ Операцію скасовано")

# 📊 /report — GPT-звіт із Binance + аналіз
@bot.message_handler(commands=["report"])
def report_handler(message):
    try:
        report_text, report_file = generate_daily_report()
        bot.send_message(chat_id=message.chat.id, text=report_text, parse_mode="Markdown")
        with open(report_file, "rb") as f:
            bot.send_document(chat_id=message.chat.id, document=f)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при формуванні звіту: {str(e)}")
# ✅ /confirm_sell — підтвердження продажу
@bot.message_handler(commands=["confirm_sell"])
def confirm_sell(message):
    assets_to_sell = [
        {"asset": "TRX", "amount": 24},
        {"asset": "XRP", "amount": 9.99},
        {"asset": "GFT", "amount": 74},
        {"asset": "TRUMP", "amount": 1.5}
    ]
    try:
        for asset in assets_to_sell:
            symbol = f"{asset['asset']}USDT"
            client.create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=asset["amount"]
            )
        save_trade_history(assets_to_sell, action="sell")
        bot.reply_to(message, "✅ Продаж виконано та збережено в історії.")
    except Exception as e:
        if "INSUFFICIENT_BALANCE" in str(e):
            bot.reply_to(message, "⚠️ Недостатньо балансу для продажу.")
        else:
            bot.reply_to(message, f"❌ Помилка під час продажу: {str(e)}")

# ✅ /confirm_buy — підтвердження купівлі
@bot.message_handler(commands=["confirm_buy"])
def confirm_buy(message):
    assets_to_buy = [
        {"asset": "ADA", "amount": 15},
        {"asset": "HBAR", "amount": 80},
        {"asset": "NOT", "amount": 90}
    ]
    try:
        for asset in assets_to_buy:
            symbol = f"{asset['asset']}USDT"
            client.create_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quantity=asset["amount"]
            )
        save_trade_history(assets_to_buy, action="buy")
        bot.reply_to(message, "✅ Купівля виконана та збережена в історії.")
    except Exception as e:
        if "INSUFFICIENT_BALANCE" in str(e):
            bot.reply_to(message, "⚠️ Недостатньо балансу для купівлі.")
        else:
            bot.reply_to(message, f"❌ Помилка під час купівлі: {str(e)}")

# 🧠 Inline підтвердження купівлі (демо-режим)
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

@bot.message_handler(commands=["confirm_buy_inline"])
def confirm_buy_inline(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Підтвердити купівлю", callback_data="buy_now"))
    bot.send_message(message.chat.id, "Підтверди купівлю криптовалюти:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "buy_now")
def execute_buy(call):
    assets_to_buy = [
        {"asset": "ADA", "amount": 15},
        {"asset": "HBAR", "amount": 80},
        {"asset": "NOT", "amount": 90}
    ]
    try:
        for asset in assets_to_buy:
            symbol = f"{asset['asset']}USDT"
            client.create_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quantity=asset["amount"]
            )
        save_trade_history(assets_to_buy, action="buy")
        bot.edit_message_text("✅ Купівля виконана!", call.message.chat.id, call.message.message_id)
    except Exception as e:
        if "INSUFFICIENT_BALANCE" in str(e):
            bot.send_message(call.message.chat.id, "⚠️ Недостатньо балансу для купівлі.")
        else:
            bot.send_message(call.message.chat.id, f"❌ Помилка: {str(e)}")


# 📘 /history — повна історія угод з групуванням по датах
@bot.message_handler(commands=["history"])
def handle_history(message):
    history_file = "trade_history.json"

    if not os.path.exists(history_file):
        bot.send_message(chat_id=message.chat.id, text="📭 Історія порожня.")
        return

    with open(history_file, "r") as f:
        history = json.load(f)

    if not history:
        bot.send_message(chat_id=message.chat.id, text="📭 Історія ще не збережена.")
        return

    text = "📘 *ІСТОРІЯ УГОД*:\n"
    grouped = {}

    for item in history:
        date = item["date"].split(" ")[0]
        grouped.setdefault(date, []).append(item)

    for date, entries in grouped.items():
        text += f"\n📆 {date}:\n"
        for e in entries:
            emoji = "✅" if e["action"] == "buy" else "❌"
            text += f"- {emoji} {e['action'].upper()} {e['asset']} — {e['amount']}\n"

    bot.send_message(chat_id=message.chat.id, text=text, parse_mode="Markdown")
# 📱 Головне меню кнопок
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        ["💰 Баланс", "📊 Звіт", "📘 Історія"],
        ["✅ Підтвердити купівлю", "✅ Підтвердити продаж"],
        ["🔄 Оновити", "🛑 Скасувати"]
    ],
    resize_keyboard=True
)

# 💰 Баланс — кнопка
@bot.message_handler(func=lambda message: message.text == "💰 Баланс")
def handle_balance(message):
    try:
        account_info = client.get_account()
        balances = [b for b in account_info["balances"] if float(b["free"]) > 0 or float(b["locked"]) > 0]

        text = "💼 *Твій баланс:*\n"
        for b in balances:
            total = float(b["free"]) + float(b["locked"])
            if total > 0:
                text += f"- {b['asset']}: {total}\n"

        bot.send_message(message.chat.id, text, parse_mode="Markdown")
    except Exception as e:
        if "INSUFFICIENT_BALANCE" in str(e):
            bot.send_message(message.chat.id, "⚠️ Недостатньо балансу для операції.")
        else:
            bot.send_message(message.chat.id, f"❌ Помилка при отриманні балансу: {str(e)}")

# 📘 Історія — кнопка
@bot.message_handler(func=lambda message: message.text == "📘 Історія")
def handle_history_button(message):
    handle_history(message)

# 📊 Звіт — кнопка
@bot.message_handler(func=lambda message: message.text == "📊 Звіт")
def handle_report_button(message):
    report_handler(message)

# 🔄 Оновити — кнопка
@bot.message_handler(func=lambda message: message.text == "🔄 Оновити")
def handle_refresh(message):
    bot.send_message(message.chat.id, "🔄 Дані оновлено (реалізація триває)")

# 🛑 Скасувати — кнопка
@bot.message_handler(func=lambda message: message.text == "🛑 Скасувати")
def handle_cancel(message):
    bot.send_message(message.chat.id, "❌ Операцію скасовано")
# 🟢 /start і /help — стартове повідомлення
@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    text = (
        "👋 Привіт! Я GPT-асистент Binance.\n\n"
        "🔸 Щодня о 09:00 та 20:00 я надсилаю аналітику.\n"
        "🔸 Ти можеш підтвердити дії:\n"
        "   - /confirm_sell — підтвердити продаж\n"
        "   - /confirm_buy — підтвердити купівлю\n"
        "   - /report — аналітика GPT\n"
        "   - /history — історія твоїх угод\n"
        "   - /set_budget 100 — встановити бюджет\n"
        "   - /buy BTC 0.01 — купити вручну\n"
        "   - /sell ETH 0.5 — продати вручну\n"
        "   - /status — переглянути бюджет\n\n"
        "💰 Я зберігаю всі твої операції автоматично!"
    )
    bot.reply_to(message, text, reply_markup=main_menu)

# ✅ Запуск бота
if __name__ == "__main__":
    bot.infinity_polling()
