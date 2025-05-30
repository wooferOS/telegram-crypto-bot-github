# 📦 main.py — Telegram бот для GPT-аналітики Binance

import logging
import os
import json
from dotenv import load_dotenv
from telebot import TeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from binance.client import Client
from daily_analysis import main as generate_daily_report  # GPT-звіт з daily_analysis.py
from telebot.types import CallbackQuery
from datetime import datetime

# Завантаження змінних з .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

bot = TeleBot(TELEGRAM_TOKEN)
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

# 📱 Головне меню кнопок
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        ["💰 Баланс", "📊 Звіт", "📘 Історія"],
        ["✅ Підтвердити купівлю", "✅ Підтвердити продаж"],
        ["🔄 Оновити", "🛑 Скасувати"]
    ], resize_keyboard=True)

# 📊 Перевірка бюджету перед купівлею
def check_budget(amount):
    try:
        with open("budget.json", "r") as f:
            b = json.load(f)
        return (b["used"] + amount) <= b["budget"]
    except:
        return False
# 🟢 /start і /help
@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    logging.info(f"DEBUG: /start або /help від {message.chat.username}")
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
    bot.reply_to(message, text, reply_markup=get_main_keyboard())

# 🔘 Кнопка: Баланс
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
# 📊 Кнопка: Звіт
@bot.message_handler(func=lambda m: m.text == "📊 Звіт")
def report_btn(message):
    report_handler(message)

# 📈 Команда /report — GPT-аналітика
@bot.message_handler(commands=["report"])
def report_handler(message):
    try:
        import asyncio
        result = asyncio.run(generate_daily_report())
        if result is None:
            bot.send_message(message.chat.id, "❌ Помилка при формуванні GPT-звіту.")
            return

        report_text, report_file = result
        bot.send_message(message.chat.id, report_text, parse_mode="Markdown")
        with open(report_file, "rb") as f:
            bot.send_document(message.chat.id, f)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка при формуванні звіту: {str(e)}")

# 📘 Кнопка: Історія
@bot.message_handler(func=lambda m: m.text == "📘 Історія")
def history_btn(message):
    handle_history(message)

# 📘 Команда /history — історія угод
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
# ✅ Кнопка: Підтвердити купівлю
@bot.message_handler(func=lambda m: m.text == "✅ Підтвердити купівлю")
def confirm_buy_button(message):
    bot.send_message(message.chat.id, "🛒 Виклик підтвердження купівлі через /confirm_buy")

# ✅ Кнопка: Підтвердити продаж
@bot.message_handler(func=lambda m: m.text == "✅ Підтвердити продаж")
def confirm_sell_button(message):
    bot.send_message(message.chat.id, "💸 Виклик підтвердження продажу через /confirm_sell")

# 🛑 Кнопка: Скасувати
@bot.message_handler(func=lambda m: m.text == "🛑 Скасувати")
def cancel(message):
    bot.send_message(message.chat.id, "❌ Операцію скасовано")

# 🔄 Кнопка: Оновити
@bot.message_handler(func=lambda m: m.text == "🔄 Оновити")
def refresh(message):
    bot.send_message(message.chat.id, "🔄 Дані оновлено (реалізація триває)")
# ✅ /confirm_sell — виконати продаж
@bot.message_handler(commands=["confirm_sell"])
def confirm_sell(message):
    assets = [
        {"asset": "AMB", "amount": 0.73},
        {"asset": "GFT", "amount": 74},
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

# ✅ /confirm_buy_inline — кнопка підтвердження купівлі
@bot.message_handler(commands=["confirm_buy_inline"])
def confirm_buy_inline(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Підтвердити купівлю", callback_data="buy_now"))
    bot.send_message(message.chat.id, "Підтверди купівлю криптовалюти:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "buy_now")
def execute_buy(call):
    assets = [
        {"asset": "XRP", "amount": 10},
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

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirmbuy_"))
def handle_confirm_buy(call):
    coin = call.data.split("_")[1]
    bot.answer_callback_query(call.id)

    try:
        quantity = 15 / float(client.get_symbol_ticker(symbol=f"{coin}USDT")["price"])  # Купуємо на 15 USDT
        quantity = round(quantity, 6)  # округлення до 6 знаків
        order = client.create_order(
            symbol=f"{coin}USDT",
            side="BUY",
            type="MARKET",
            quantity=quantity
        )
        bot.send_message(call.message.chat.id, f"✅ Куплено {quantity} {coin} на 15 USDT.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Помилка при купівлі {coin}: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirmsell_"))
def handle_confirm_sell(call):
    coin = call.data.split("_")[1]
    bot.answer_callback_query(call.id)

    try:
        balance = client.get_asset_balance(asset=coin)
        quantity = round(float(balance["free"]), 6)
        order = client.create_order(
            symbol=f"{coin}USDT",
            side="SELL",
            type="MARKET",
            quantity=quantity
        )
        bot.send_message(call.message.chat.id, f"✅ Продано {quantity} {coin}.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Помилка при продажу {coin}: {e}")

    # Зберегти в історію
    price = float(client.get_symbol_ticker(symbol=f"{coin}USDT")["price"])
    save_trade_history([
        {
            "asset": coin,
            "amount": quantity,
            "price": price,
            "value": round(quantity * price, 2)
        }
    ], action="sell")


# 💸 Ручна купівля /buy BTC 0.01
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

# 💰 Ручний продаж /sell ETH 0.5
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

# 📊 /status — перегляд бюджету
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

# /set_budget 100
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
        


# ✅ Запуск бота
if __name__ == "__main__":
    print("🚀 Бот запущено!")
    bot.polling(none_stop=True)



