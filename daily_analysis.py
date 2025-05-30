# daily_analysis.py — оновлена логіка GPT-аналізу ринку

import os
import json
from datetime import datetime
import requests
from dotenv import load_dotenv
from binance.client import Client
from openai import OpenAI
from telegram import Bot

# Завантаження змінних
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
UAH_RATE = 43.0  # фіксований курс гривні

# Ініціалізація клієнтів
client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
openai = OpenAI(api_key=OPENAI_API_KEY)

# Whitelist пар для аналізу
WHITELIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT", "XRPUSDT", "DOTUSDT", "AVAXUSDT",
    "DOGEUSDT", "TRXUSDT", "LINKUSDT", "LTCUSDT", "SHIBUSDT", "UNIUSDT", "FETUSDT", "OPUSDT",
    "INJUSDT", "PEPEUSDT", "WLDUSDT", "SUIUSDT", "1000SATSUSDT", "STRKUSDT", "NOTUSDT", "TRUMPUSDT",
    "XRPTUSD", "GMTUSDT", "ARBUSDT", "HBARUSDT", "ATOMUSDT", "GMTUSDC"
]
# Отримання змін по ринку для whitelist монет
def get_market_data():
    changes = {}
    tickers = client.get_ticker()
    for t in tickers:
        symbol = t['symbol']
        if symbol in WHITELIST:
            changes[symbol] = {
                "price": float(t["lastPrice"]),
                "percent_change": float(t["priceChangePercent"]),
                "volume": float(t["volume"])
            }
    return changes

# Отримання балансу гаманця з Binance
def get_balance():
    account = client.get_account()
    balances = {}
    for b in account['balances']:
        asset = b['asset']
        free = float(b['free'])
        if free > 0:
            if asset + "USDT" in WHITELIST:
                balances[asset] = free
    return balances
# Генерація GPT-звіту на основі балансу та ринку
def generate_gpt_report(market_data, balances):
    report_lines = []
    report_lines.append("📊 Звіт портфелю (щоденна аналітика)")
    report_lines.append("")
    report_lines.append("💰 Баланс:")

    for symbol, qty in balances.items():
        symbol_full = symbol + "USDT"
        if symbol_full in market_data:
            price = market_data[symbol_full]["price"]
            usdt_value = qty * price
            uah_value = usdt_value * UAH_RATE
            report_lines.append(f"{symbol}: {qty:.4f} × {price:.6f} = {usdt_value:.2f} USDT ≈ {uah_value:.2f}₴")

    report_lines.append("")
    report_lines.append("🔼 Купити (потенціал на 24 години):")

    top_to_buy = sorted(market_data.items(), key=lambda x: x[1]["percent_change"], reverse=True)[:3]
    for symbol, data in top_to_buy:
        coin = symbol.replace("USDT", "").replace("TUSD", "").replace("USDC", "")
        report_lines.append(f"- {coin}: {data['percent_change']}% за добу, обʼєм: {data['volume']:.0f}")
        report_lines.append(f"  Команда: /confirmbuy{coin}")

    return "\n".join(report_lines)
# Основна функція: аналіз + Telegram-звіт
def main():
    try:
        market_data = get_market_data()
        balances = get_balance()
        report = generate_gpt_report(market_data, balances)
        path = save_report(report)
        send_telegram(report)
        return report, path
    except Exception as e:
        send_telegram(f"❌ Помилка в аналізі: {str(e)}")
        return None

# Надсилання звіту в Telegram
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("❌ Telegram error:", e)
# Збереження звіту в папку reports/YYYY-MM-DD/daily_report_HH-MM.md
def save_report(text):
    now = datetime.now()
    folder = f"reports/{now.strftime('%Y-%m-%d')}"
    os.makedirs(folder, exist_ok=True)
    path = f"{folder}/daily_report_{now.strftime('%H-%M')}.md"
    with open(path, "w") as f:
        f.write(text)
    return path

# Запуск скрипта
if __name__ == "__main__":
    main()
