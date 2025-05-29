# 📦 main.py — Telegram бот для криптоасистента з підтвердженнями та аналітикою

# ✅ ЧАСТИНА 1: Імпорти, .env, ініціалізація bot та Binance client
import os
import json
from dotenv import load_dotenv
from telebot import TeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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

def check_budget(amount):
    with open("budget.json", "r") as f:
        b = json.load(f)
    return (b["used"] + amount) <= b["budget"]

# 📱 Головне меню кнопок
main_menu = ReplyKeyboardMarkup(resize_keyboard=True)
main_menu.row("💰 Баланс", "📊 Звіт", "📘 Історія")
main_menu.row("✅ Підтвердити купівлю", "✅ Підтвердити продаж")
main_menu.row("🔄 Оновити", "🛑 Скасувати")


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
        "   - /history — історія твоїх угод\n"
        "   - /set_budget 100 — встановити бюджет\n"
        "   - /buy BTC 0.01 — купити вручну\n"
        "   - /sell ETH 0.5 — продати вручну\n"
        "   - /status — переглянути бюджет\n\n"
        "💰 Я зберігаю всі твої операції автоматично!"
    )
    bot.reply_to(message, text, reply_markup=main_menu)

# 🔁 Обробники кнопок / команд (рефакторинг)
@bot.message_handler(func=lambda m: m.text == "📘 Історія")
def history_btn(m): handle_history(m)

@bot.message_handler(func=lambda m: m.text == "📊 Звіт")
def report_btn(m): report_handler(m)

@bot.message_handler(func=lambda m: m.text == "🔄 Оновити")
def refresh(m): bot.send_message(m.chat.id, "🔄 Дані оновлено (реалізація триває)")

@bot.message_handler(func=lambda m: m.text == "🛑 Скасувати")
def cancel(m): bot.send_message(m.chat.id, "❌ Операцію скасовано")

# 📘 /history
@bot.message_handler(commands=["history"])
def handle_history(message):
    history_file = "trade_history.json"
    if not os.path.exists(history_file):
        bot.send_message(message.chat.id, "📭 Історія порожня.")
        return
    with open(history_file, "r") as f:
        history = json.load(f)
    if not history:
        bot.send_message(message.chat.id, "📭 Історія ще не збережена.")
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
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# 📊 /report
@bot.message_handler(commands=["report"])
def report_handler(message):
    try:
        report_text, report_file = generate_daily_report()
        bot.send_message(message.chat.id, report_text, parse_mode="Markdown")
        with open(report_file, "rb") as f:
            bot.send_document(message.chat.id, f)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при формуванні звіту: {str(e)}")

# ✅ /confirm_sell
@bot.message_handler(commands=["confirm_sell"])
def confirm_sell(message):
    assets = [
        {"asset": "TRX", "amount": 24},
        {"asset": "XRP", "amount": 9.99},
        {"asset": "GFT", "amount": 74},
        {"asset": "TRUMP", "amount": 1.5}
    ]
    try:
        for asset in assets:
            symbol = f"{asset['asset']}USDT"
            client.create_order(symbol=symbol, side="SELL", type="MARKET", quantity=asset["amount"])
        save_trade_history(assets, action="sell")
        bot.reply_to(message, "✅ Продаж виконано та збережено в історії.")
    except Exception as e:
        msg = "⚠️ Недостатньо балансу." if "INSUFFICIENT_BALANCE" in str(e) else f"❌ Помилка: {str(e)}"
        bot.reply_to(message, msg)

# ✅ confirm_buy_inline
@bot.message_handler(commands=["confirm_buy_inline"])
def confirm_buy_inline(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Підтвердити купівлю", callback_data="buy_now"))
    bot.send_message(message.chat.id, "Підтверди купівлю криптовалюти:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "buy_now")
def execute_buy(call):
    assets = [
        {"asset": "ADA", "amount": 15},
        {"asset": "HBAR", "amount": 80},
        {"asset": "NOT", "amount": 90}
    ]
    total = sum([a["amount"] for a in assets])
    if not check_budget(total):
        bot.send_message(call.message.chat.id, "⚠️ Перевищено бюджет.")
        return
    try:
        for asset in assets:
            symbol = f"{asset['asset']}USDT"
            client.create_order(symbol=symbol, side="BUY", type="MARKET", quantity=asset["amount"])
        save_trade_history(assets, action="buy")
        with open("budget.json", "r") as f:
            b = json.load(f)
        b["used"] += total
        with open("budget.json", "w") as f:
            json.dump(b, f)
        bot.edit_message_text(call.message.chat.id, call.message.message_id, "✅ Купівля виконана.")
    except Exception as e:
        msg = "⚠️ Недостатньо балансу." if "INSUFFICIENT_BALANCE" in str(e) else f"❌ Помилка: {str(e)}"
        bot.send_message(call.message.chat.id, msg)

# 💰 Баланс
@bot.message_handler(func=lambda m: m.text == "💰 Баланс")
def handle_balance(message):
    try:
        account_info = client.get_account()
        balances = [b for b in account_info["balances"] if float(b["free"]) > 0 or float(b["locked"]) > 0]
        text = "💼 *Твій баланс:*\n"
        for b in balances:
            total = float(b["free"]) + float(b["locked"])
            text += f"- {b['asset']}: {total}\n"
        bot.send_message(message.chat.id, text, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при отриманні балансу: {str(e)}")

# /set_budget
@bot.message_handler(commands=["set_budget"])
def set_budget(message):
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            bot.reply_to(message, "❗️ Формат: /set_budget 100")
            return
        new_budget = float(parts[1])
        with open("budget.json", "r") as f:
            b = json.load(f)
        b["budget"] = new_budget
        with open("budget.json", "w") as f:
            json.dump(b, f)
        bot.reply_to(message, f"✅ Новий бюджет встановлено: *{new_budget}* USDT", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

# /status
@bot.message_handler(commands=["status"])
def status(message):
    try:
        with open("budget.json", "r") as f:
            b = json.load(f)
        used = b["used"]
        budget = b["budget"]
        percent = round((used / budget) * 100, 2) if budget else 0
        bot.reply_to(message, f"📊 *Бюджет*: {used} / {budget} USDT (*{percent}% використано*)", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

# /buy
@bot.message_handler(commands=["buy"])
def manual_buy(message):
    try:
        parts = message.text.strip().split()
        if len(parts) != 3:
            bot.reply_to(message, "❗️ Формат: /buy BTC 0.01")
            return
        asset, amount = parts[1].upper(), float(parts[2])
        if not check_budget(amount):
            bot.reply_to(message, "⚠️ Перевищено бюджет.")
            return
        symbol = f"{asset}USDT"
        client.create_order(symbol=symbol, side="BUY", type="MARKET", quantity=amount)
        save_trade_history([{"asset": asset, "amount": amount}], action="buy")
        with open("budget.json", "r") as f:
            b = json.load(f)
        b["used"] += amount
        with open("budget.json", "w") as f:
            json.dump(b, f)
        bot.reply_to(message, f"✅ Купівля {amount} {asset} виконана.")
    except Exception as e:
        msg = "⚠️ Недостатньо балансу." if "INSUFFICIENT_BALANCE" in str(e) else f"❌ Помилка: {str(e)}"
        bot.reply_to(message, msg)

# /sell
@bot.message_handler(commands=["sell"])
def manual_sell(message):
    try:
        parts = message.text.strip().split()
        if len(parts) != 3:
            bot.reply_to(message, "❗️ Формат: /sell ETH 0.5")
            return
        asset, amount = parts[1].upper(), float(parts[2])
        symbol = f"{asset}USDT"
        client.create_order(symbol=symbol, side="SELL", type="MARKET", quantity=amount)
        save_trade_history([{"asset": asset, "amount": amount}], action="sell")
        bot.reply_to(message, f"✅ Продаж {amount} {asset} виконано.")
    except Exception as e:
        msg = "⚠️ Недостатньо активу." if "INSUFFICIENT_BALANCE" in str(e) else f"❌ Помилка: {str(e)}"
        bot.reply_to(message, msg)

# ✅ Запуск бота
if __name__ == "__main__":
    bot.polling(none_stop=True)
