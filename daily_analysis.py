import os
import json
from datetime import datetime
from dotenv import load_dotenv
import requests
from binance.client import Client
from openai import OpenAI
from telegram import Bot

# Завантажити змінні середовища
load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
tg_bot = Bot(token=TELEGRAM_TOKEN)
openai = OpenAI(api_key=OPENAI_API_KEY)

SNAPSHOT_FILE = "balance_snapshot.json"
EXCLUDED_ASSETS = ["USDT", "BUSD", "USDC"]
def get_binance_balance():
    try:
        account_info = client.get_account()
        balances = {
            item["asset"]: float(item["free"]) + float(item["locked"])
            for item in account_info["balances"]
            if float(item["free"]) + float(item["locked"]) > 0
        }
        return balances
    except Exception as e:
        print(f"❌ Binance Error: {e}")
        return {}

def get_current_prices():
    try:
        prices = client.get_all_tickers()
        return {item["symbol"]: float(item["price"]) for item in prices}
    except Exception as e:
        print(f"❌ Price Fetch Error: {e}")
        return {}

def get_usdt_to_uah_rate():
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=USDTUAH"
        response = requests.get(url)
        return float(response.json().get("price", 0))
    except Exception as e:
        print(f"❌ UAH Rate Error: {e}")
        return 0

def send_report_via_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": ADMIN_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
SNAPSHOT_FILE = "balance_snapshot.json"

def load_previous_snapshot():
    if not os.path.exists(SNAPSHOT_FILE):
        return {}
    try:
        with open(SNAPSHOT_FILE, "r") as file:
            return json.load(file)
    except Exception as e:
        print(f"❌ Snapshot Load Error: {e}")
        return {}

def save_current_snapshot(balance_data, prices=None):
    snapshot = {}
    for symbol, amount in balance_data.items():
        if prices:
            price_key = f"{symbol}USDT"
            price = prices.get(price_key, 0)
            snapshot[symbol] = {
                "amount": amount,
                "avg_price": price
            }
        else:
            snapshot[symbol] = {
                "amount": amount,
                "avg_price": 0
            }
    try:
        with open(SNAPSHOT_FILE, "w") as file:
            json.dump(snapshot, file, indent=2)
    except Exception as e:
        print(f"❌ Snapshot Save Error: {e}")
def run_daily_analysis():
    try:
        balance_data = get_binance_balance()
        if not balance_data:
            send_report_via_telegram("❌ Неможливо отримати баланс з Binance.")
            return

        prices = get_current_prices()
        if not prices:
            send_report_via_telegram("❌ Неможливо отримати ціни з Binance.")
            return

        rate_uah = get_usdt_to_uah_rate()
        if not rate_uah:
            send_report_via_telegram("❌ Неможливо отримати курс USDT→UAH.")
            return

        previous_snapshot = load_previous_snapshot()
        save_current_snapshot(balance_data, prices)

        total_usdt = 0
        messages = []
        suggestions = []

        for symbol, amount in balance_data.items():
            if symbol in EXCLUDED_ASSETS:
                continue

            price_key = f"{symbol}USDT"
            price = prices.get(price_key)
            if not price:
                continue

            usdt_value = round(amount * price, 2)

            snapshot_value = previous_snapshot.get(symbol, {})
            avg_price = snapshot_value.get("avg_price", price) if isinstance(snapshot_value, dict) else price

            pnl = round((price - avg_price) * amount, 2)
            pnl_percent = round((pnl / (avg_price * amount)) * 100, 2) if avg_price else 0
            uah_value = round(usdt_value * rate_uah)

            total_usdt += usdt_value

            # Повідомлення по активу
            messages.append(
                f"*{symbol}*\n"
                f"Кількість: `{amount}`\n"
                f"Ціна: `${price}` | Середня: `${avg_price}`\n"
                f"📊 PnL: `${pnl}` ({pnl_percent}%)\n"
                f"💰 Вартість: `${usdt_value}` / `{uah_value}₴`\n"
            )

            # Генерація рекомендації
            if pnl_percent > 3:
                suggestions.append(f"📤 Продати {symbol} (PnL: {pnl_percent}%)")
            elif pnl_percent < -3:
                suggestions.append(f"📥 Купити {symbol} (PnL: {pnl_percent}%)")

        report = "\n".join(messages)
        summary = f"\n\n📦 Загальна вартість портфеля: `${round(total_usdt, 2)}` ≈ `{round(total_usdt * rate_uah)}₴`\n"
        if suggestions:
            summary += "\n📌 *Рекомендації:*\n" + "\n".join(suggestions)

        send_report_via_telegram(report + summary)

    except Exception as e:
        send_report_via_telegram(f"❌ Помилка аналізу: {e}")
        print(f"❌ Run Analysis Error: {e}")
