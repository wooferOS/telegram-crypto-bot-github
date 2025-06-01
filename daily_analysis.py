import os
import json
from datetime import datetime
from dotenv import load_dotenv
import requests
from binance.client import Client
from openai import OpenAI
from telegram import Bot

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
EXCLUDED_ASSETS = ["BUSD", "USDC"]
def get_binance_balance():
    try:
        balances = client.get_account()["balances"]
        return {
            asset["asset"]: float(asset["free"]) + float(asset["locked"])
            for asset in balances
            if float(asset["free"]) + float(asset["locked"]) > 0
        }
    except Exception as e:
        print(f"❌ Binance Balance Error: {e}")
        return {}

def get_current_prices():
    try:
        tickers = client.get_all_tickers()
        return {t["symbol"]: float(t["price"]) for t in tickers}
    except Exception as e:
        print(f"❌ Binance Prices Error: {e}")
        return {}

def get_usdt_to_uah_rate():
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTUAH")
        return float(res.json()["price"])
    except Exception as e:
        print(f"❌ USDT Rate Error: {e}")
        return None
SNAPSHOT_FILE = "balance_snapshot.json"

def load_previous_snapshot():
    try:
        with open(SNAPSHOT_FILE, "r") as file:
            return json.load(file)
    except:
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
        
def send_report_via_telegram(message: str):
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

            if symbol == "USDT":
                total_usdt += amount
                messages.append(
                    f"*{symbol}*\n"
                    f"Кількість: `{amount}`\n"
                    f"Ціна: `1.0` | Середня: `1.0`\n"
                    f"📊 PnL: `0.0` (0.0%)\n"
                    f"💰 Вартість: `{amount}` USDT / `{round(amount * rate_uah)}₴`\n"
                )
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
            messages.append(
                f"*{symbol}*\n"
                f"Кількість: `{amount}`\n"
                f"Ціна: `{price}` | Середня: `{avg_price}`\n"
                f"📊 PnL: `{pnl}` ({pnl_percent}%)\n"
                f"💰 Вартість: `{usdt_value}` USDT / `{uah_value}₴`\n"
            )
            # 💡 Генерація інвестиційних порад
            if pnl_percent < -5:
                suggestions.append(f"🔻 *{symbol}* має значне падіння — розглянь можливість _продажу_.")
            elif pnl_percent > 5:
                suggestions.append(f"🟢 *{symbol}* показує ріст — розглянь можливість _фіксації прибутку_.")
        # 📦 Додавання загальної інформації
        messages.append(f"\n📦 *Загальна вартість портфеля:* `{round(total_usdt, 2)}` USDT ≈ `{round(total_usdt * rate_uah)}₴`")

        # 📨 Формування повного звіту
        final_message = "\n".join(messages)
        if suggestions:
            final_message += "\n\n📈 *Рекомендації:*\n" + "\n".join(suggestions)

        send_report_via_telegram(final_message)
    except Exception as e:
        send_report_via_telegram(f"❌ Помилка аналізу: {e}")
if __name__ == "__main__":
    run_daily_analysis()
