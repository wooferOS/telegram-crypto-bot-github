import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from binance.client import Client
from openai import OpenAI
from telegram import Bot
import requests

# 🔐 Завантаження змінних середовища
load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
tg_bot = Bot(token=TELEGRAM_TOKEN)
openai = OpenAI(api_key=OPENAI_API_KEY)

# ⚪ WHITELIST монет
WHITELIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "DOTUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT", "LTCUSDT", "BCHUSDT", "XLMUSDT",
    "ATOMUSDT", "ETCUSDT", "FILUSDT", "HBARUSDT", "VETUSDT", "ICPUSDT", "RUNEUSDT", "SANDUSDT",
    "EGLDUSDT", "AAVEUSDT", "NEARUSDT", "FTMUSDT", "AXSUSDT", "THETAUSDT"
]

EXCLUDED_ASSETS = ["USDT", "BUSD", "TUSD", "USDC", "FDUSD"]

LOG_FILE = "daily.log"
# 📉 Курс USDT → UAH (можна під'єднати реальний API)
def get_usdt_to_uah_rate():
    return 39.2  # Приклад: курс ПриватБанку або MonoBank

# 📊 Отримати баланс
def get_binance_balance():
    balances = client.get_account()["balances"]
    result = {}
    for asset in balances:
        total = float(asset["free"]) + float(asset["locked"])
        if total > 0:
            result[asset["asset"]] = round(total, 6)
    return result

# 💵 Отримати поточні ціни (всі пари)
def get_current_prices():
    prices = client.get_all_tickers()
    return {p["symbol"]: float(p["price"]) for p in prices}

# 💾 Завантажити попередній знімок балансу
def load_previous_snapshot():
    try:
        with open("balance_snapshot.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# 💾 Зберегти поточний знімок
def save_current_snapshot(snapshot):
    with open("balance_snapshot.json", "w") as f:
        json.dump(snapshot, f, indent=2)
# 🧾 Формування звіту Markdown
def format_report(balance_info, total_usdt, sell_recommendations, buy_recommendations):
    lines = ["*📊 Звіт по портфелю Binance:*", ""]

    for item in balance_info:
        lines.append(f"🔹 *{item['symbol']}*")
        lines.append(f"  - Кількість: {item['amount']}")
        lines.append(f"  - Вартість: {item['usdt_value']:.2f} USDT ≈ {item['uah_value']:.0f} грн")
        lines.append(f"  - Середня ціна: {item['avg_price']:.4f} USDT")
        lines.append(f"  - PNL: {item['pnl']:+.2f} USDT ({item['pnl_percent']:+.2f}%)")
        lines.append("")

    lines.append(f"*💰 Загальна вартість:* {total_usdt:.2f} USDT\n")

    if sell_recommendations:
        lines.append("*📉 Рекомендації на продаж:*")
        for rec in sell_recommendations:
            lines.append(f"🔻 {rec['symbol']} — прогноз слабкий, потенціал низький")
        lines.append("")

    if buy_recommendations:
        lines.append("*📈 Рекомендації на купівлю:*")
        for rec in buy_recommendations:
            lines.append(f"🟢 {rec['symbol']} — дохідність: {rec['expected_profit']:.2f}%")
            lines.append(f"    ▪ Стоп-лосс: {rec['stop_loss']} ▪ Тейк-профіт: {rec['take_profit']}")
        lines.append("")

    return "\n".join(lines)

# 📤 Надіслати звіт у Telegram
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
def run_daily_analysis():
    try:
        balance_data_raw = get_binance_balance()
        if not balance_data_raw:
            send_report_via_telegram("❌ Неможливо отримати баланс з Binance.")
            return

        prices = get_current_prices()
        if not prices:
            send_report_via_telegram("❌ Неможливо отримати ціни з Binance.")
            return

        rate_uah = get_usdt_to_uah_rate()
        previous_snapshot = load_previous_snapshot()
        save_current_snapshot(balance_data_raw)

        total_usdt = 0
        balance_info = []

        for symbol, amount in balance_data_raw.items():
            if symbol in EXCLUDED_ASSETS:
                continue
            price_key = f"{symbol}USDT"
            if price_key not in prices:
                continue
            price = prices[price_key]
            usdt_value = round(amount * price, 2)
            avg_price = previous_snapshot.get(symbol, {}).get("avg_price", price)
            pnl = round((price - avg_price) * amount, 2)
            pnl_percent = round((pnl / (avg_price * amount)) * 100, 2) if avg_price else 0
            uah_value = round(usdt_value * rate_uah)

            total_usdt += usdt_value
            balance_info.append({
                "symbol": symbol,
                "amount": amount,
                "usdt_value": usdt_value,
                "avg_price": avg_price,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
                "uah_value": uah_value
            })

        # 🔎 Генерація умовних рекомендацій (заглушки, замінити GPT)
        sell_recommendations = [i for i in balance_info if i["pnl_percent"] < -5]
        buy_recommendations = [{
            "symbol": sym.replace("USDT", ""),
            "expected_profit": 4.5,
            "stop_loss": "3%",
            "take_profit": "7%"
        } for sym in WHITELIST[:3]]  # топ-3

        report = format_report(balance_info, total_usdt, sell_recommendations, buy_recommendations)
        send_report_via_telegram(report)
        return report

    except Exception as e:
        send_report_via_telegram(f"❌ Помилка в аналізі: {str(e)}")
        return None

# ▶️ Локальний запуск
if __name__ == "__main__":
    run_daily_analysis()
