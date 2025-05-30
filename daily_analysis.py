import os
import json
import time
import logging
from datetime import datetime
from binance.client import Client
from openai import OpenAI
import requests


BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# Ініціалізація логування
logging.basicConfig(filename="daily.log", level=logging.INFO, format="%(asctime)s %(levelname)s:%(message)s")

def log_message(message):
    logging.info(message)
    print(message)

# Ініціалізація OpenAI та Binance клієнтів
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
binance_client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
# Параметри
WHITELIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "DOTUSDT", "LINKUSDT", "TRXUSDT", "MATICUSDT", "SHIBUSDT", "LTCUSDT", "BCHUSDT", "TONUSDT",
    "ICPUSDT", "NEARUSDT", "APTUSDT", "HBARUSDT", "FILUSDT", "INJUSDT", "RNDRUSDT", "ARBUSDT",
    "SUIUSDT", "PEPEUSDT", "1000SATSUSDT", "NOTUSDT", "STRKUSDT", "TRUMPUSDT"
]
UAH_RATE = 43.0  # курс USDT до гривні (налаштовується вручну)

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "Markdown"})
def get_balance():
    balances = binance_client.get_account()["balances"]
    result = {}
    for asset in balances:
        symbol = asset["asset"]
        free = float(asset["free"])
        if free > 0:
            if symbol == "USDT":
                result[symbol] = free
            else:
                try:
                    price = float(binance_client.get_symbol_ticker(symbol=f"{symbol}USDT")["price"])
                    result[symbol] = {"amount": free, "price": price}
                except:
                    continue
    client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)  # Ініціалізація клієнта
tickers = client.get_ticker_24hr()  # Отримання всіх тикерів за 24h

def get_market_data():
    btc_data = client.get_ticker(symbol="BTCUSDT")
    market_data = {}
    for item in tickers:
        symbol = item["symbol"]
        if symbol in WHITELIST:
            try:
                market_data[symbol] = {
                    "price": float(item["lastPrice"]),
                    "volume": float(item["quoteVolume"]),
                    "change": float(item["priceChangePercent"])
                }
            except Exception as e:
                continue
    return market_data

def analyze_profit_opportunities(balance_data, market_data):
    sell_suggestions = []
    buy_suggestions = []
    usdt_balance = balance_data.get("USDT", 0)

    for asset, info in balance_data.items():
        if asset == "USDT":
            continue
        symbol = f"{asset}USDT"
        if symbol in market_data:
            change = market_data[symbol]["change"]
            if change < -1:
                sell_suggestions.append({
                    "symbol": asset,
                    "amount": info["amount"],
                    "price": info["price"],
                    "change": change,
                    "cmd": f"/confirmsell{asset}"
                })

    # buy_suggestions генеруються пізніше на основі обробленого market_data
    return sell_suggestions, buy_suggestions


    for symbol, info in market_data.items():
        asset = symbol.replace("USDT", "")
        if info["change"] > 0.5:
            buy_suggestions.append({
                "symbol": asset,
                "price": info["price"],
                "change": info["change"],
                "volume": info["volume"],
                "cmd": f"/confirmbuy{asset}"
            })

    return sell_suggestions, buy_suggestions, usdt_balance
def build_markdown_report(balance_data, sell_list, buy_list, usdt_balance):
    lines = [f"📊 GPT-звіт (станом на {datetime.now().strftime('%Y-%m-%d %H:%M')})", ""]

    lines.append("💰 *Баланс:*")
    for asset, info in balance_data.items():
        if asset == "USDT":
            lines.append(f"- USDT: {info:.2f} ≈ {info * UAH_RATE:.2f}₴")
        else:
            total = info["amount"] * info["price"]
            lines.append(f"- {asset}: {info['amount']:.4f} × {info['price']:.4f} = {total:.2f} USDT ≈ {total * UAH_RATE:.2f}₴")

    lines.append("")

    if sell_list:
        lines.append("🔻 *Продати:*")
        for item in sell_list:
            lines.append(f"- {item['symbol']}: {item['amount']:.2f} × {item['price']:.4f} ≈ {item['amount'] * item['price']:.2f} USDT")
            lines.append(f"  Причина: зміна {item['change']:.2f}%, команда: `{item['cmd']}`")
    else:
        lines.append("🔻 Продати: немає явних кандидатів")

    lines.append("")
    if buy_list:
        lines.append("🔼 *Купити (прогноз на 24 години):*")
        for item in buy_list:
            expected_profit = usdt_balance * item["change"] / 100
            lines.append(f"- {item['symbol']}: зміна {item['change']:.2f}%, обʼєм: {int(item['volume'])}")
            lines.append(f"  Очікуваний прибуток ≈ {expected_profit:.2f} USDT, команда: `{item['cmd']}`")
    else:
        lines.append("🔼 Купити: не знайдено підходящих активів")

    lines.append("")
    expected_total_profit = sum(usdt_balance * item["change"] / 100 for item in buy_list)
    lines.append(f"📈 *Очікуваний прибуток на добу:* ≈ {expected_total_profit:.2f} USDT")

    return "\n".join(lines)
def save_report(report_text):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M")

    folder = f"reports/{date_str}"
    os.makedirs(folder, exist_ok=True)

    filepath = f"{folder}/daily_report_{time_str}.md"
    with open(filepath, "w") as f:
        f.write(report_text)

    return filepath
def main():
    try:
        log_message("🔁 Запуск daily_analysis.py")

        market_data = get_market_data()
        balance_data = get_balance()
        sell_list, buy_list, usdt_balance = analyze_profit_opportunities(balance_data, market_data)
        report_text = build_markdown_report(balance_data, sell_list, buy_list, usdt_balance)
        file_path = save_report(report_text)

        log_message("✅ Звіт сформовано та збережено.")
        send_telegram("✅ *GPT-звіт сформовано.* Надсилаю файл...")
        with open(file_path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
                data={"chat_id": ADMIN_CHAT_ID},
                files={"document": f}
            )
    except Exception as e:
        logging.error(f"❌ Помилка в аналізі: {str(e)}")
        try:
            send_telegram(f"❌ Помилка у виконанні: {str(e)}")
        except:
            pass
if __name__ == "__main__":
    main()
