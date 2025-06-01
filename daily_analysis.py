import os
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
from dotenv import load_dotenv

# Завантаження змінних середовища
load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
tg_bot = Bot(token=TELEGRAM_TOKEN)
openai = OpenAI(api_key=OPENAI_API_KEY)

# Список дозволених торгових пар
WHITELIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "DOTUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT", "LTCUSDT", "BCHUSDT", "XLMUSDT",
    "ATOMUSDT", "ETCUSDT", "FILUSDT", "HBARUSDT", "VETUSDT", "ICPUSDT", "RUNEUSDT", "SANDUSDT",
    "EGLDUSDT", "AAVEUSDT", "NEARUSDT", "FTMUSDT", "AXSUSDT", "THETAUSDT"
]

# Валюти, які не слід аналізувати (наприклад, нативні стейблкоїни)
EXCLUDED_ASSETS = ["USDT", "BUSD", "TUSD", "USDC", "FDUSD"]

# Шлях до лог-файлу
LOG_FILE = "daily.log"

# Отримати поточний курс USDT до UAH (псевдо-реальне значення для прикладу)
def get_usdt_to_uah_rate():
    return 39.2  # 🟡 можна підключити API ПриватБанк або MonoBank
# Отримати баланс акаунту
def get_binance_balance():
    balances = client.get_account()["balances"]
    result = {}
    for asset in balances:
        free = float(asset["free"])
        locked = float(asset["locked"])
        total = free + locked
        if total > 0:
            result[asset["asset"]] = round(total, 6)
    return result
# Отримати поточну ціну пари (наприклад, BTCUSDT)
def get_symbol_price(symbol):
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])
# Формування звіту в Telegram
def format_report(balance_info, sell_recommendations, buy_recommendations):
    lines = []
    lines.append("*📊 Звіт по портфелю:*")
    lines.append("")
    total_usdt = 0

    for asset in balance_info:
        amount = asset["amount"]
        usdt_value = asset["usdt_value"]
        avg_price = asset["avg_price"]
        pnl = asset["pnl"]
        pnl_percent = asset["pnl_percent"]
        ua_value = asset["uah_value"]
        total_usdt += usdt_value

        lines.append(f"🔹 {asset['symbol']}")
        lines.append(f"  - Кількість: {amount}")
        lines.append(f"  - Вартість: {usdt_value:.2f} USDT ≈ {ua_value:.0f} грн")
        lines.append(f"  - Середня ціна: {avg_price:.4f} USDT")
        lines.append(f"  - PNL: {pnl:+.2f} USDT ({pnl_percent:+.2f}%)")
        lines.append("")

    lines.append(f"*Загальна вартість:* {total_usdt:.2f} USDT")
    lines.append("")

    if sell_recommendations:
        lines.append("*📉 Рекомендації на продаж:*")
        for rec in sell_recommendations:
            lines.append(f"🔻 {rec['symbol']} — прогноз слабкий, потенціал низький")
        lines.append("")

    if buy_recommendations:
        lines.append("*📈 Рекомендації на купівлю:*")
        for rec in buy_recommendations:
            lines.append(
                f"🟢 {rec['symbol']} — очікувана дохідність: {rec['expected_profit']:.2f}%"
            )
            lines.append(f"    ▪ Стоп-лосс: {rec['stop_loss']} ▪ Тейк-профіт: {rec['take_profit']}")
        lines.append("")

    return "\n".join(lines)
# Надсилання звіту в Telegram
def send_report_via_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": ADMIN_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        log.error(f"❌ Помилка надсилання звіту в Telegram: {e}")
# Основна функція
def run_daily_analysis():
    log.info("🔍 Запуск щоденного аналізу...")

    balance_data = get_binance_balance()
    if not balance_data:
        send_report_via_telegram("❌ Неможливо отримати баланс з Binance.")
        return

    prices = get_current_prices()
    if not prices:
        send_report_via_telegram("❌ Неможливо отримати ціни з Binance.")
        return

    # 🔄 Завантажити попередній баланс для PNL
    previous_snapshot = load_previous_snapshot()
    save_current_snapshot(balance_data)

    # 📊 Обробка балансу
    report_lines = []
    total_usdt = 0
    total_usdt_yesterday = 0
    for asset, data in balance_data.items():
        price = prices.get(f"{asset}USDT", 0)
        value = round(data["free"] * price, 2)
        avg_price = data.get("avg_price", price)
        pnl = round((price - avg_price) * data["free"], 2)
        pnl_pct = round((price - avg_price) / avg_price * 100, 2) if avg_price else 0
        pnl_text = f"{pnl} USDT ({pnl_pct}%)"

        yesterday_value = previous_snapshot.get(asset, {}).get("value", 0)
        change_pct = round((value - yesterday_value) / yesterday_value * 100, 2) if yesterday_value else 0
        report_lines.append(f"*{asset}*: {data['free']} → {value} USDT | Середня: {avg_price} | PNL: {pnl_text} | Зміна: {change_pct}%")

        total_usdt += value
        total_usdt_yesterday += yesterday_value

    # 📈 Загальна зміна
    total_change_pct = round((total_usdt - total_usdt_yesterday) / total_usdt_yesterday * 100, 2) if total_usdt_yesterday else 0
    report_header = f"*📊 Звіт Binance*\n\n💼 Поточна вартість: {total_usdt} USDT\n📉 Зміна за добу: {total_change_pct}%\n\n"

    full_report = report_header + "\n".join(report_lines)
    send_report_via_telegram(full_report)

# ✅ Завантажити попередній знімок балансу
def load_previous_snapshot():
    try:
        with open("balance_snapshot.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# ✅ Зберегти поточний знімок балансу
def save_current_snapshot(snapshot):
    with open("balance_snapshot.json", "w") as f:
        json.dump(snapshot, f, indent=2)

if __name__ == "__main__":
    run_daily_analysis()
