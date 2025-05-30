import os
import json
import logging
from datetime import datetime
from binance.client import Client
from openai import OpenAI
import requests

# Функція логування
def log_message(message: str):
    import logging
    logging.basicConfig(filename="daily.log", level=logging.INFO, format="%(asctime)s %(levelname)s:%(message)s")
    logging.info(message)

# Функція надсилання повідомлення у Telegram
def send_telegram(message: str):
    import requests, os
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": message})

# Ініціалізація ключів
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Клієнти
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
# Логування
logging.basicConfig(filename="daily.log", level=logging.INFO, format="%(asctime)s %(levelname)s:%(message)s")

# Каталог для збереження звітів
def ensure_report_dir():
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join("reports", today)
    os.makedirs(path, exist_ok=True)
    return path

# Список whitelist пар для аналізу
WHITELIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT",
    "DOTUSDT", "MATICUSDT", "AVAXUSDT", "SHIBUSDT", "LINKUSDT", "TRXUSDT", "LTCUSDT",
    "BCHUSDT", "ATOMUSDT", "XLMUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "IMXUSDT", "PEPEUSDT",
    "RNDRUSDT", "1000SATSUSDT", "TIAUSDT", "WIFUSDT", "JASMYUSDT", "NOTUSDT", "STRKUSDT", "TRUMPUSDT"
]
# Отримати поточний баланс з Binance
def get_current_balance():
    try:
        balances = client.get_account()["balances"]
        result = []
        for asset in balances:
            asset_name = asset["asset"]
            free = float(asset["free"])
            if free > 0:
                symbol = asset_name + "USDT"
                try:
                    price = float(client.get_symbol_ticker(symbol=symbol)["price"])
                    result.append({
                        "symbol": symbol,
                        "asset": asset_name,
                        "amount": free,
                        "price": price,
                        "value": round(free * price, 2)
                    })
                except:
                    continue
        return result
    except Exception as e:
        logging.error(f"❌ Помилка при отриманні балансу: {str(e)}")
        return []
# Отримати whitelist монет з ринку Binance
def get_market_whitelist_data():
    try:
        tickers = client.ticker_24hr()
        filtered = []
        for t in tickers:
            symbol = t["symbol"]
            if symbol in WHITELIST and symbol.endswith("USDT"):
                try:
                    price_change_percent = float(t["priceChangePercent"])
                    volume = float(t["quoteVolume"])
                    filtered.append({
                        "symbol": symbol,
                        "price_change_percent": price_change_percent,
                        "volume": volume
                    })
                except:
                    continue
        return sorted(filtered, key=lambda x: x["price_change_percent"], reverse=True)
    except Exception as e:
        logging.error(f"❌ Помилка при аналізі ринку: {str(e)}")
        return []
# Побудувати GPT-звіт
def build_gpt_report(balance_summary, market_whitelist):
    try:
        total_usdt = sum([coin["usdt_value"] for coin in balance_summary])
        sorted_market = market_whitelist[:5]
        sorted_balance = sorted(balance_summary, key=lambda x: x["usdt_value"], reverse=True)

        prompt = f"""
Твоя роль — GPT-аналітик для трейдингу. Сформуй короткий, чіткий звіт на 24 години з урахуванням:

1. Поточний баланс:
{json.dumps(balance_summary, indent=2, ensure_ascii=False)}

2. Топ монети з whitelist з найбільшим потенціалом:
{json.dumps(sorted_market, indent=2, ensure_ascii=False)}

Завдання:
- Які монети з балансу варто продати, чому?
- Які монети з whitelist купити, чому?
- Який очікуваний прибуток у % і USDT через 24 години?
- Додай команди типу /confirmsellXRP /confirmbuyBTC
- Обовʼязково додай Stop Loss і Take Profit для кожної купівлі
- Твоя відповідь українською мовою, лаконічно

Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

        chat_completion = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ти — досвідчений криптоаналітик Binance."},
                {"role": "user", "content": prompt}
            ]
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"❌ Помилка генерації GPT-звіту: {str(e)}")
        return "❌ GPT-звіт недоступний."
# Створити .md файл звіту
def save_report_to_file(gpt_text, prefix="daily_report"):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H-%M")
        report_dir = os.path.join("reports", today)
        os.makedirs(report_dir, exist_ok=True)
        filename = os.path.join(report_dir, f"{prefix}_{time_str}.md")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(gpt_text)
        return filename
    except Exception as e:
        logging.error(f"❌ Помилка збереження GPT-звіту: {str(e)}")
        return None


# Надіслати звіт у Telegram
def send_report_to_telegram(report_text, report_file):
    try:
        if TELEGRAM_TOKEN and ADMIN_CHAT_ID:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": ADMIN_CHAT_ID, "text": report_text, "parse_mode": "Markdown"})
            if os.path.exists(report_file):
                files = {"document": open(report_file, "rb")}
                doc_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
                requests.post(doc_url, data={"chat_id": ADMIN_CHAT_ID}, files=files)
    except Exception as e:
        logging.error(f"❌ Помилка надсилання звіту в Telegram: {str(e)}")
# Основна функція для щоденного запуску
def main():
    try:
        log_message("🔁 Запуск daily_analysis.py")

        # Крок 1: Отримання балансу
        balances = get_binance_balances()

        # Крок 2: Отримання ринкових даних
        market_data = get_market_data()

        # Крок 3: Побудова звіту GPT
        report_text = generate_gpt_report(balances, market_data)

        # Крок 4: Збереження та надсилання звіту
        report_file = save_report_to_file(report_text)
        if report_file:
            send_report_to_telegram(report_text, report_file)
            log_message(f"✅ Звіт сформовано: {report_file}")
        else:
            log_message("⚠️ Звіт не збережено.")
    except Exception as err:
        error_message = f"❌ Помилка в аналізі: {str(err)}"
        logging.error(error_message)
        send_telegram(error_message)
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception("❌ Фатальна помилка у виконанні скрипта:")
        try:
            send_telegram(f"❌ Помилка у виконанні: {str(e)}")
        except:
            pass
