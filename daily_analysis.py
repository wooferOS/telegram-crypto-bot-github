import os
import json
import logging
from datetime import datetime
from binance.client import Client
from binance.exceptions import BinanceAPIException
from openai import OpenAI
import requests
from telegram import Bot, ParseMode
import traceback

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Ініціалізація клієнтів
client = Client(api_key=os.getenv("BINANCE_API_KEY"), api_secret=os.getenv("BINANCE_SECRET_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
bot = Bot(token=TELEGRAM_TOKEN)

# Шлях до whitelist
WHITELIST_PATH = "whitelist.json"
REPORTS_DIR = "reports"
LOG_FILE = "daily.log"
UAH_RATE = 43.0
# Налаштування логування
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(levelname)s:%(message)s")

def log_message(message):
    print(message)
    logging.info("🔁 Запуск daily_analysis.py")

def send_telegram(message):
    telegram_token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID")
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data)
    except Exception as e:
        logging.error(f"❌ Telegram Error: {str(e)}")
def save_to_file(data, filename):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

def load_from_file(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}

def save_report(content, date_str, hour_min):
    folder = f"reports/{date_str}"
    os.makedirs(folder, exist_ok=True)
    path = f"{folder}/daily_report_{hour_min}.md"
    with open(path, "w") as f:
        f.write(content)
    return path
def analyze_balance(client):
    balances = get_binance_balances(client)
    result = []
    for asset in balances:
        symbol = asset["asset"]
        free = float(asset["free"])
        if free == 0 or symbol == "USDT":
            continue
        pair = symbol + "USDT"
        try:
            price = float(client.get_symbol_ticker(symbol=pair)["price"])
            value = round(price * free, 2)
            result.append({
                "symbol": symbol,
                "amount": free,
                "value_usdt": value,
                "pair": pair
            })
        except Exception as e:
            log.error(f"❌ Не вдалося отримати ціну для {pair}: {str(e)}")
    return sorted(result, key=lambda x: x["value_usdt"], reverse=True)

def get_whitelist():
    return [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
        "XRPUSDT", "DOGEUSDT", "LINKUSDT", "MATICUSDT", "TRXUSDT",
        "ADAUSDT", "DOTUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT",
        "NEARUSDT", "XLMUSDT", "INJUSDT", "OPUSDT", "ARBUSDT",
        "TIAUSDT", "SUIUSDT", "PEPEUSDT", "FETUSDT", "RNDRUSDT",
        "SEIUSDT", "ORDIUSDT", "1000SATSUSDT", "JASMYUSDT", "ENJUSDT"
    ]
def get_market_data(client, whitelist):
    tickers = client.get_ticker()
    market_data = {}
    for t in tickers:
        symbol = t["symbol"]
        if symbol in whitelist:
            try:
                change = float(t["priceChangePercent"])
                volume = float(t["quoteVolume"])
                last_price = float(t["lastPrice"])
                market_data[symbol] = {
                    "change": change,
                    "volume": volume,
                    "last_price": last_price
                }
            except:
                continue
    return market_data

def prepare_analysis(balance_data, market_data):
    to_sell = []
    to_buy = []
    for asset in balance_data:
        pair = asset["pair"]
        if pair in market_data:
            perf = market_data[pair]["change"]
            if perf < -2:  # умовно слабка монета
                to_sell.append({**asset, "change": perf})

    sorted_market = sorted(market_data.items(), key=lambda x: (x[1]["change"], x[1]["volume"]), reverse=True)
    for symbol, data in sorted_market[:3]:  # топ 3 монети на купівлю
        to_buy.append({
            "pair": symbol,
            "change": data["change"],
            "volume": data["volume"],
            "price": data["last_price"]
        })

    return to_sell, to_buy
def estimate_profit(buy_entry, sell_entry):
    try:
        profit = (sell_entry["price"] - buy_entry["price"]) * (buy_entry["usdt"] / buy_entry["price"])
        return round(profit, 2)
    except:
        return 0.0

def format_trade_command(action, symbol):
    return f"/confirm{action.lower()}{symbol.replace('/', '')}"

def generate_report(balance_usdt, to_sell, to_buy, currency_rate):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = f"# 📊 Звіт GPT-аналітики ({now})\n\n"
    report += f"**Поточний баланс:** {balance_usdt:.2f} USDT ≈ {balance_usdt * currency_rate:.2f} грн\n\n"

    report += "## 🔻 Рекомендовано продати:\n"
    if to_sell:
        for asset in to_sell:
            report += f"- {asset['asset']} ({asset['pair']}): {asset['usdt']:.2f} USDT — зміна {asset['change']}%\n"
            report += f"  👉 {format_trade_command('sell', asset['pair'])}\n"
    else:
        report += "Немає слабких активів для продажу.\n"

    report += "\n## 🟢 Рекомендовано купити:\n"
    if to_buy:
        for asset in to_buy:
            report += f"- {asset['pair']}: зміна +{asset['change']}%, обʼєм {asset['volume']:.2f}\n"
            report += f"  👉 {format_trade_command('buy', asset['pair'])}\n"
    else:
        report += "Немає вигідних монет для купівлі.\n"

    return report
def ensure_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)

def save_report(text, report_dir):
    now = datetime.now().strftime("%H-%M")
    filename = f"daily_report_{now}.md"
    path = os.path.join(report_dir, filename)
    with open(path, "w") as f:
        f.write(text)
    return path

def send_telegram_report(text, path=None):
    try:
        bot.send_message(chat_id=ADMIN_CHAT_ID, text="📤 Новий звіт GPT-аналітики:", parse_mode=ParseMode.MARKDOWN)
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                bot.send_document(chat_id=ADMIN_CHAT_ID, document=f)
        else:
            bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logging.error(f"❌ Помилка при надсиланні в Telegram: {e}")
        
def get_binance_balances(client):
    try:
        account_info = client.get_account()
        balances = account_info.get("balances", [])
        result = {}
        for asset in balances:
            asset_name = asset["asset"]
            free = float(asset["free"])
            locked = float(asset["locked"])
            total = free + locked
            if total > 0:
                result[asset_name] = total
        return result
    except Exception as e:
        logging.error(f"❌ Не вдалося отримати баланс Binance: {str(e)}")
        return {}
        
def build_gpt_prompt(balances, market_data):
    prompt = "Оціни мій криптопортфель і порадь, що продати, що купити:\n\n"
    prompt += "Поточні активи:\n"
    for asset, amount in balances.items():
        prompt += f"- {asset}: {amount}\n"
    prompt += "\nАктуальні ринкові дані:\n"
    for symbol, data in market_data.items():
        prompt += f"- {symbol}: {data['change']}% змін, обʼєм {data['volume']}, ціна {data['last_price']}\n"
    prompt += "\nРезультат подай у вигляді рекомендацій з обґрунтуванням."
    return prompt
    
def ask_gpt(prompt):
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ти фінансовий аналітик крипторинку."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"❌ GPT-помилка: {e}")
        return "❌ Не вдалося отримати відповідь від GPT."

def main():
    try:
        log_message("🔁 Запуск daily_analysis.py")
        
        # 1. Отримати баланс
        balances = get_binance_balances(client)

        # 2. Отримати ринкові дані
        whitelist = get_whitelist()
        market_data = get_market_data(client, whitelist)

        # 3. Побудувати GPT-запит
        prompt = build_gpt_prompt(balances, market_data)

        # 4. Запит до GPT
        analysis = ask_gpt(prompt)

        # 5. Зберегти звіт
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_dir = os.path.join("reports", date_str)
        ensure_directory(report_dir)
        report_path = save_report(analysis, report_dir)

        # 6. Надіслати в Telegram
        send_telegram_report(analysis, report_path)

    except Exception as err:
        logging.error("❌ Фатальна помилка у виконанні скрипта:")
        logging.error(traceback.format_exc())
        try:
            send_telegram(f"❌ Помилка у виконанні: {str(err)}")
        except:
            pass
if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        error_message = f"❌ Помилка в аналізі: {str(err)}"
        logging.error(error_message)
        try:
            if TELEGRAM_TOKEN and ADMIN_CHAT_ID:
                send_telegram(f"❌ Фатальна помилка у виконанні скрипта:\n{error_message}")
        except Exception as send_err:
            logging.error(f"Не вдалося надіслати повідомлення у Telegram: {str(send_err)}")

