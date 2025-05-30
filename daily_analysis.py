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
    """
    Формує GPT-звіт:
    - Аналіз активів на балансі
    - Визначає, що продавати
    - Визначає, що купувати
    - Розраховує очікуваний прибуток
    """
    from datetime import datetime

    assets_to_sell = []
    assets_to_buy = []
    expected_profit_usdt = 0

    # Визначаємо кандидати на продаж з балансу
    for asset, info in balances.items():
        if asset == "USDT":
            continue
        price_change = market_data.get(asset + "/USDT", {}).get("price_change_percent", 0)
        if price_change < -1:  # просідання за добу > 1%
            assets_to_sell.append((asset, info["amount"], info["value_usdt"], price_change))

    # Визначаємо найперспективніші активи для купівлі
    potential_buys = []
    for pair, data in market_data.items():
        if "/USDT" not in pair:
            continue
        symbol = pair.replace("/USDT", "")
        if symbol in balances:
            continue  # не пропонуємо купити те, що вже маємо
        if data["price_change_percent"] > 2 and data["volume"] > 100000:
            potential_buys.append((symbol, data["price_change_percent"], data["volume"]))

    potential_buys.sort(key=lambda x: -x[1])
    assets_to_buy = potential_buys[:3]  # топ-3 для купівлі

    # Оцінка прибутку
    if assets_to_sell and assets_to_buy:
        sell_usdt = assets_to_sell[0][2]
        buy_gain_percent = assets_to_buy[0][1]
        expected_profit_usdt = round(sell_usdt * (buy_gain_percent / 100), 2)

    # Формуємо Markdown-звіт
    report = "📊 GPT-звіт (станом на {})\n\n".format(datetime.now().strftime("%Y-%m-%d %H:%M"))

    if assets_to_sell:
        report += "🔻 Продати:\n"
        for asset, amount, value, change in assets_to_sell:
            report += f"- {asset}: {amount:.4f} ≈ {value:.2f} USDT ({change:+.2f}%)\n"
            report += f"  Команда: /confirmsell{asset}\n"
    else:
        report += "🔻 Продати: немає явних кандидатів\n"

    report += "\n"

    if assets_to_buy:
        report += "🔼 Купити:\n"
        for symbol, change, volume in assets_to_buy:
            report += f"- {symbol}: {change:+.2f}% за добу, обʼєм: {volume}\n"
            report += f"  Команда: /confirmbuy{symbol}\n"
    else:
        report += "🔼 Купити: не знайдено підходящих активів\n"

    report += "\n📈 Очікуваний прибуток: "
    report += f"+{expected_profit_usdt:.2f} USDT за добу\n" if expected_profit_usdt else "недостатньо даних\n"

    return report

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
