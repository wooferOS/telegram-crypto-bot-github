# 📦 main.py — Telegram бот для криптоасистента з підтвердженнями та аналітикою

import os
import telebot
import json
from telegram import ReplyKeyboardMarkup
from binance.client import Client
from dotenv import load_dotenv
from daily_analysis import save_trade_history, generate_daily_report

# 🧪 Завантаження .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

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
        bot.reply_to(message, f"❌ Помилка під час купівлі: {str(e)}")

# 📘 /history — перегляд історії угод
@bot.message_handler(commands=["history"])
def history(message):
    history_file = "trade_history.json"
    if not os.path.exists(history_file):
        bot.reply_to(message, "⛔️ Історія пуста.")
        return

    with open(history_file, "r") as f:
        data = json.load(f)

    if not data:
        bot.reply_to(message, "⛔️ Історія ще не записана.")
        return

    history_lines = []
    for entry in data[-10:]:  # останні 10
        line = f"{entry['date']}: {entry['action'].upper()} {entry['amount']} {entry['asset']}"
        history_lines.append(line)

    response = "📚 Останні угоди:\n" + "\n".join(history_lines)
    bot.reply_to(message, response)

# 🟢 /start і /help
@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    text = (
        "👋 Привіт! Я GPT-асистент Binance.\n\n"
        "🔸 Щодня о 09:00 та 20:00 я надсилаю аналітику.\n"
        "🔸 Ти можеш підтвердити дії:\n"
        "   - /confirm_sell — підтвердити продаж\n"
        "   - /confirm_buy — підтвердити купівлю\n"
        "   - /report — аналітика GPT\n"
        "   - /history — історія твоїх угод\n\n"
        "💰 Я зберігаю всі твої операції автоматично!"
    )
    bot.reply_to(message, text, reply_markup=main_menu)

# 📱 Меню кнопок
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        ["💰 Баланс", "📊 Звіт", "📘 Історія"],
        ["✅ Підтвердити купівлю", "✅ Підтвердити продаж"],
        ["🔄 Оновити", "🛑 Скасувати"]
    ],
    resize_keyboard=True
)

@bot.message_handler(commands=["history"])
def handle_history(message):
    history_file = "trade_history.json"
    if not os.path.exists(history_file):
        bot.send_message(chat_id=message.chat.id, text="Історія порожня 🕰️")
        return

    with open(history_file, "r") as f:
        history = json.load(f)

    if not history:
        bot.send_message(chat_id=message.chat.id, text="Історія ще не збережена.")
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


# 🚀 Запуск бота
bot.infinity_polling()
