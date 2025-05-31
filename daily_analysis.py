import os
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

import json
import logging
from datetime import datetime
from binance.client import Client
from binance.exceptions import BinanceAPIException
from openai import OpenAI
import requests
from telegram import Bot
from telegram.constants import ParseMode
import traceback
import asyncio

# Логування
LOG_FILE = "daily.log"
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(levelname)s:%(message)s")
# Завантаження змінних із .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

# Ініціалізація клієнтів
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)

# Константи
WHITELIST_PATH = "whitelist.json"
UAH_RATE = 43.0  # курс гривні
# Отримати баланс з Binance
def get_binance_balance():
    balances = client.get_account()["balances"]
    result = {}
    for asset in balances:
        free = float(asset["free"])
        if free > 0:
            symbol = asset["asset"]
            if symbol.endswith("UP") or symbol.endswith("DOWN"):
                continue
            result[symbol] = free
    return result

# Завантажити whitelist
def load_whitelist():
    if os.path.exists(WHITELIST_PATH):
        with open(WHITELIST_PATH, "r") as f:
            return json.load(f)
    return []

# Отримати поточну ціну монети в USDT
def get_price(symbol):
    try:
        if symbol == "USDT":
            return 1.0
        return float(client.get_symbol_ticker(symbol=f"{symbol}USDT")["price"])
    except Exception:
        return None
# Форматувати число з 2 знаками після коми
def fmt(x):
    return f"{x:.2f}"

# GPT-запит на базі опису ринку
async def ask_gpt(prompt):
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ти криптоаналітик. Давай чіткі торгові рекомендації за 24-годинною динамікою. Не додавай фраз типу 'я не фінансовий радник'."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"❌ GPT-помилка: {e}")
        return "GPT недоступний. Спробуйте пізніше."
# Завантажити whitelist монет
def load_whitelist():
    try:
        with open(WHITELIST_PATH, "r") as f:
            return json.load(f)
    except:
        return []

# Отримати актуальний баланс у Binance
def get_current_holdings():
    holdings = {}
    prices = client.get_all_tickers()
    ticker_price = {item["symbol"]: float(item["price"]) for item in prices}

    account = client.get_account()
    for balance in account["balances"]:
        asset = balance["asset"]
        free = float(balance["free"])
        if free > 0:
            symbol = asset + "USDT"
            price = ticker_price.get(symbol, 0)
            holdings[asset] = {
                "amount": free,
                "price": price,
                "value_usdt": free * price
            }
    return holdings
# PNL для кожної монети на основі попередніх цін
def load_previous_snapshot():
    try:
        with open("prev_snapshot.json", "r") as f:
            return json.load(f)
    except:
        return {}

def save_current_snapshot(data):
    with open("prev_snapshot.json", "w") as f:
        json.dump(data, f)

def calculate_daily_pnl(current, previous):
    pnl = {}
    for asset, info in current.items():
        prev_info = previous.get(asset)
        if prev_info:
            change = ((info["price"] - prev_info["price"]) / prev_info["price"]) * 100
            pnl[asset] = round(change, 2)
        else:
            pnl[asset] = 0.0
    return pnl

def convert_to_uah(usdt_amount):
    return round(usdt_amount * UAH_RATE, 2)
def format_portfolio_report(balance_info, pnl_data, recommendations, total_expected_profit):
    lines = ["📊 *Щоденний звіт по портфелю*",
             f"🕒 Станом на: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]

    lines.append("*💼 Баланс:*")
    for asset, data in balance_info.items():
        usdt_val = round(data["usdt_value"], 2)
        avg_price = data.get("avg_price", "—")
        pnl = pnl_data.get(asset, 0)
        uah_val = convert_to_uah(usdt_val)
        lines.append(f"• {asset}: {data['amount']} (~{usdt_val} USDT | {uah_val} UAH) | Середня ціна: {avg_price} | PNL: {pnl}%")
    lines.append("")

    lines.append("*📉 Рекомендовано продати:*")
    if recommendations["sell"]:
        for item in recommendations["sell"]:
            lines.append(f"• {item['symbol']}: прогноз слабкий, продача вигідна")
    else:
        lines.append("• Нічого не рекомендовано продавати.")
    lines.append("")

    lines.append("*📈 Рекомендовано купити:*")
    if recommendations["buy"]:
        for item in recommendations["buy"]:
            sl = item.get("stop_loss")
            tp = item.get("take_profit")
            lines.append(f"• {item['symbol']}: вигідна динаміка | Очікуваний прибуток: {item['expected_profit']}% | SL: {sl} | TP: {tp}")
    else:
        lines.append("• Немає актуальних покупок на добу.")
    lines.append("")

    lines.append(f"💰 *Сумарний очікуваний прибуток за добу:* ~{total_expected_profit}%")

    return "\n".join(lines)
async def generate_daily_report():
    try:
        balance_info = get_portfolio_balance()
        prices = get_whitelist_prices()
        pnl_data = calculate_pnl(balance_info)
        recommendations = analyze_market(prices, balance_info)
        total_expected_profit = round(sum(item["expected_profit"] for item in recommendations["buy"]), 2)

        report = format_portfolio_report(balance_info, pnl_data, recommendations, total_expected_profit)
        logging.info("✅ GPT-звіт сформовано")

        bot.send_message(chat_id=ADMIN_CHAT_ID, text=report, parse_mode=ParseMode.MARKDOWN)
        logging.info("📤 Звіт надіслано в Telegram")

    except Exception as e:
        logging.error(f"❌ Помилка під час створення звіту: {e}")
        traceback.print_exc()
        bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ Помилка під час створення звіту:\n{e}")
def run_daily_analysis():
    asyncio.run(generate_daily_report())


if __name__ == "__main__":
    run_daily_analysis()
    
# 📘 Кінець файлу daily_analysis.py
# 🔁 Цей скрипт запускається щодня через GitHub Actions або вручну
# 🚀 Створює звіт, надсилає в Telegram, прогнозує угоди
