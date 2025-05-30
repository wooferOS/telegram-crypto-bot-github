import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from binance.client import Client
from openai import OpenAI
import requests

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

bot = requests.Session()
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
bot = Bot(token=TELEGRAM_TOKEN)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": ADMIN_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = bot.post(url, json=payload)
        if not response.ok:
            logging.error(f"Telegram error: {response.text}")
    except Exception as e:
        logging.error(f"Telegram send exception: {str(e)}")



WHITELIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "AVAXUSDT",
    "XRPUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT", "DOGEUSDT", "DOTUSDT",
    "OPUSDT", "ARBUSDT", "FETUSDT", "INJUSDT", "RNDRUSDT", "TIAUSDT",
    "PYTHUSDT", "WIFUSDT", "1000SATSUSDT", "PEPEUSDT", "LTCUSDT",
    "HBARUSDT", "NOTUSDT", "TRUMPUSDT", "STRKUSDT", "JUPUSDT", "SUIUSDT", "SEIUSDT"
]

def log_message(message: str):
    with open("daily.log", "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

def get_usdt_price(symbol):
    try:
        ticker = client.get_symbol_ticker(symbol=symbol + "USDT")
        return float(ticker["price"])
    except Exception:
        return 0.0

def get_binance_balance():
    balances = client.get_account()["balances"]
    result = {}
    for b in balances:
        asset = b["asset"]
        free = float(b["free"])
        if free > 0:
            result[asset] = round(free, 8)
    return result

def get_market_data():
    tickers = client.get_ticker()
    result = {}
    for t in tickers:
        symbol = t["symbol"]
        if symbol not in WHITELIST:
            continue
        try:
            price_change = float(t["priceChangePercent"])
            volume = float(t["quoteVolume"])
            result[symbol] = {
                "change": price_change,
                "volume": round(volume, 2)
            }
        except Exception:
            continue
    return result
def analyze_portfolio(balance: dict, market: dict) -> tuple:
    to_sell = []
    to_buy = []

    for asset, amount in balance.items():
        symbol = asset + "USDT"
        if symbol in market:
            change = market[symbol]["change"]
            if change < -2.0:  # монета просіла більше ніж на 2% — кандидат на продаж
                price = get_usdt_price(asset)
                value = round(amount * price, 2)
                to_sell.append({
                    "asset": asset,
                    "amount": amount,
                    "price": price,
                    "value": value,
                    "change": change
                })

    sorted_market = sorted(market.items(), key=lambda x: x[1]["change"], reverse=True)
    for symbol, data in sorted_market[:3]:  # топ-3 монети для купівлі
        asset = symbol.replace("USDT", "")
        change = data["change"]
        volume = data["volume"]
        if asset not in balance:
            to_buy.append({
                "asset": asset,
                "change": change,
                "volume": volume
            })

    return to_sell, to_buy
def generate_stop_loss_take_profit(price: float) -> tuple:
    stop_loss = round(price * 0.97, 6)     # -3%
    take_profit = round(price * 1.05, 6)   # +5%
    return stop_loss, take_profit


def estimate_profit(sell_list, buy_list, budget=100):
    # Припустимо, продаємо всі з sell_list і купуємо рівними частками buy_list
    expected_total_profit = 0.0
    recommendations = []

    if not buy_list or not sell_list:
        return 0.0, []

    per_buy_amount = budget / len(buy_list)

    for buy in buy_list:
        symbol = buy["asset"] + "USDT"
        if symbol in MARKET_CACHE:
            buy_price = MARKET_CACHE[symbol]["price"]
            change = MARKET_CACHE[symbol]["change"]
            expected_profit = round(per_buy_amount * (change / 100), 2)
            expected_total_profit += expected_profit
            recommendations.append({
                "asset": buy["asset"],
                "change": change,
                "expected_profit": expected_profit,
                "buy_price": buy_price
            })

    return expected_total_profit, recommendations
def format_report(balances, sell_list, buy_list, recommendations, expected_profit_usdt):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"📊 GPT-звіт (станом на {now})\n"]

    # Баланс
    lines.append("💰 Баланс:")
    for item in balances:
        lines.append(f"{item['asset']}: {item['amount']} × {item['price']} = {item['value_usdt']} USDT ≈ {item['value_uah']}₴")

    # Продавати
    if sell_list:
        lines.append("\n🔻 Продати:")
        for item in sell_list:
            stop_loss, take_profit = generate_stop_loss_take_profit(item["price"])
            lines.append(f"- {item['asset']}: {item['value_usdt']} USDT — прогноз слабкий.")
            lines.append(f"  Команда: /confirmsell{item['asset']}")
            lines.append(f"  Стоп-лосс: {stop_loss}, Тейк-профіт: {take_profit}")
    else:
        lines.append("\n🔻 Продати: немає явних кандидатів")

    # Купити
    if buy_list:
        lines.append("\n🔼 Купити (потенціал на 24 години):")
        for item in recommendations:
            stop_loss, take_profit = generate_stop_loss_take_profit(item["buy_price"])
            lines.append(f"- {item['asset']}: {item['change']}% за добу")
            lines.append(f"  Очікуваний прибуток: {item['expected_profit']} USDT")
            lines.append(f"  Команда: /confirmbuy{item['asset']}")
            lines.append(f"  Стоп-лосс: {stop_loss}, Тейк-профіт: {take_profit}")
    else:
        lines.append("\n🔼 Купити: не знайдено підходящих активів")

    # Очікуваний прибуток
    lines.append(f"\n📈 Очікуваний прибуток: {round(expected_profit_usdt, 2)} USDT")

    return "\n".join(lines)
def generate_stop_loss_take_profit(price):
    stop_loss = round(price * 0.95, 6)  # 5% нижче
    take_profit = round(price * 1.05, 6)  # 5% вище
    return stop_loss, take_profit
def save_report_md(balance_data, sell_candidates, buy_candidates, date_str, time_str):
    lines = [f"📊 GPT-звіт (станом на {date_str} {time_str})\n"]

    lines.append("💰 Поточний баланс:")
    for asset in balance_data:
        lines.append(f"{asset['symbol']}: {asset['amount']} × {asset['price']} = {asset['value_usdt']} USDT ≈ {asset['value_uah']}₴")
    lines.append("")

    if sell_candidates:
        lines.append("🔻 Продати:")
        for asset in sell_candidates:
            sl, tp = generate_stop_loss_take_profit(asset['price'])
            lines.append(
                f"- {asset['symbol']}: прогноз {asset['change']}%, ціна: {asset['price']}, "
                f"стоп-лосс: {sl}, тейк-профіт: {tp}\n  Команда: /confirmsell{asset['symbol']}"
            )
    else:
        lines.append("🔻 Продати: немає явних кандидатів")

    lines.append("")

    if buy_candidates:
        lines.append("🔼 Купити:")
        for asset in buy_candidates:
            sl, tp = generate_stop_loss_take_profit(asset['price'])
            lines.append(
                f"- {asset['symbol']}: прогноз {asset['change']}%, ціна: {asset['price']}, "
                f"обʼєм: {asset['volume']}, стоп-лосс: {sl}, тейк-профіт: {tp}\n  Команда: /confirmbuy{asset['symbol']}"
            )
    else:
        lines.append("🔼 Купити: не знайдено підходящих активів")

    lines.append("")
    lines.append("📈 Очікуваний прибуток: буде розраховано після підтвердження")

    folder = f"reports/{date_str}"
    os.makedirs(folder, exist_ok=True)
    filename = f"{folder}/daily_report_{time_str}.md"
    with open(filename, "w") as f:
        f.write("\n".join(lines))

    return filename, "\n".join(lines)
def main():
    try:
        logging.info("🔁 Початок щоденного аналізу...")

        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H-%M")

        balances = get_binance_balance()
        balance_data = analyze_balance(balances)

        market_data = get_market_data()
        sell_candidates = find_sell_candidates(balance_data, market_data)
        buy_candidates = find_buy_candidates(market_data)

        report_path, report_text = save_report_md(balance_data, sell_candidates, buy_candidates, date_str, time_str)

        send_telegram("✅ Звіт сформовано та надіслано.")
        send_file_telegram(report_path)

        logging.info(f"✅ Звіт сформовано та надіслано. Файл: {report_path}")

    except Exception as e:
        error_message = f"❌ Помилка в аналізі: {str(e)}"
        logging.error(error_message)
        send_telegram(error_message)
if __name__ == "__main__":
    log_message("🔁 Запуск daily_analysis.py")
    today = datetime.now().strftime("%Y-%m-%d")
    time_now = datetime.now().strftime("%H-%M")

    try:
        main()
    except Exception as err:
        logging.exception("❌ Фатальна помилка у виконанні скрипта:")
        send_telegram(f"❌ Помилка у виконанні: {str(err)}")
# Створення необхідної директорії для зберігання звітів
def ensure_reports_dir():
    date_dir = os.path.join(REPORT_DIR, datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(date_dir, exist_ok=True)
    return date_dir

# Файл логування (якщо викликається напряму)
log_file = os.path.join(BASE_DIR, "daily.log")
if not os.path.exists(log_file):
    with open(log_file, "w") as f:
        f.write("")

# Кінець файлу daily_analysis.py
