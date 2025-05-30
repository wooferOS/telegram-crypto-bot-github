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

def analyze_balance(client):
    balances = get_binance_balances(client)  # {BTC: 0.004, ETH: 0.02, ...}
    result = []

    for symbol, free in balances.items():
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

def get_whitelist(client):
    """Отримує всі торгові пари з USDT на Binance."""
    return [t['symbol'] for t in client.get_ticker() if t['symbol'].endswith("USDT")]

def get_market_data(client, whitelist):
    """Формує ринкові дані (зміна %, обʼєм, остання ціна) для whitelist."""
    tickers = client.get_ticker()
    market_data = {}

    for t in tickers:
        symbol = t.get("symbol")
        if symbol in whitelist:
            try:
                change = float(t.get("priceChangePercent", 0))
                volume = float(t.get("quoteVolume", 0))
                last_price = float(t.get("lastPrice", 0))
                market_data[symbol] = {
                    "change": change,
                    "volume": volume,
                    "last_price": last_price
                }
            except Exception:
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

    # ✅ Повертаємо не тільки звіт, а й to_buy, to_sell
    return report, to_buy, to_sell

def ensure_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)

async def send_telegram_report(report, to_buy, to_sell):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = [
        [InlineKeyboardButton(f"🟢 Купити {coin}", callback_data=f"confirmbuy_{coin}")]
        for coin in to_buy
    ] + [
        [InlineKeyboardButton(f"🔴 Продати {coin}", callback_data=f"confirmsell_{coin}")]
        for coin in to_sell
    ]





    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=report, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"❌ Telegram error: {e}")


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
        
def generate_report(balance, to_sell, to_buy, uah_rate, gpt_forecast):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    report_lines = [f"📊 *Звіт GPT-аналітики ({now})*\n"]

    report_lines.append("💼 *Баланс:*")
    for coin, value in balance.items():
        report_lines.append(f"- {coin}: {value['amount']} → ≈ {round(value['usdt'], 2)} USDT")

    if to_sell:
        report_lines.append("\n📉 *Рекомендується продати:*")
        for coin in to_sell:
            reason = to_sell[coin].get("reason", "")
            report_lines.append(f"- 🔴 {coin} — {reason}\n→ `/confirmsell_{coin}`")

    if to_buy:
        report_lines.append("\n📈 *Рекомендується купити:*")
        for coin in to_buy:
            reason = to_buy[coin].get("reason", "")
            report_lines.append(f"- 🟢 {coin} — {reason}\n→ `/confirmbuy_{coin}`")

    total_profit = sum(x.get("expected_profit", 0) for x in to_buy.values())
    report_lines.append(f"\n📈 *Очікуваний прибуток:* ~{round(total_profit, 2)} USDT")

    report_lines.append(f"\n📅 *Прогноз GPT:*\n{gpt_forecast.strip()}")
    return "\n".join(report_lines)

async def main():
    try:
        log_message("🔁 Запуск daily_analysis.py")

        # 1. Отримати баланс
        balances = get_binance_balances(client)

        # 2. Отримати whitelist та ринкові дані
        whitelist = get_whitelist(client)
        market_data = get_market_data(client, whitelist)


        # 3. Побудувати GPT-запит
        prompt = build_gpt_prompt(balances, market_data)

        # 4. Запит до GPT
        analysis = ask_gpt(prompt)

        # 5. Згенерувати та надіслати фінальний Markdown-звіт
        balance_data = analyze_balance(client)
        to_sell, to_buy = prepare_analysis(balance_data, market_data)
        balance_value = sum(asset["value_usdt"] for asset in balance_data)

        report = generate_report(
            balance={a["symbol"]: {"amount": a["amount"], "usdt": a["value_usdt"]} for a in balance_data},
            to_sell={a["symbol"]: {"reason": f"зміна {a['change']}%"} for a in to_sell},
            to_buy={a["pair"]: {"reason": f"обʼєм {a['volume']} | зміна +{a['change']}%", "expected_profit": 3.5} for a in to_buy},
            uah_rate=UAH_RATE,
            gpt_forecast=analysis
        )
        await send_telegram_report(
            report,
            to_buy=[a["pair"] for a in to_buy],
            to_sell=[a["symbol"] for a in to_sell]
        )


    except Exception as err:
        logging.error("❌ Фатальна помилка у виконанні скрипта:")
        logging.error(traceback.format_exc())
        try:
            send_telegram(f"❌ Помилка у виконанні: {str(err)}")
        except:
            pass
if __name__ == "__main__":
    asyncio.run(main())



