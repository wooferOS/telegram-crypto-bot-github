import os
import json
import openai
import requests
from datetime import datetime, timedelta
from aiogram import Bot


openai.api_key = os.getenv("OPENAI_API_KEY")

BINANCE_API_BASE = "https://api.binance.com"
THRESHOLD_PNL_PERCENT = 1.0  # Мінімальний відсоток зміни для дії

def get_price(symbol: str) -> float:
    try:
        response = requests.get(f"{BINANCE_API_BASE}/api/v3/ticker/price", params={"symbol": symbol})
        return float(response.json()["price"])
    except Exception as e:
        print(f"❌ Error getting price for {symbol}: {e}")
        return 0.0

def load_previous_data(file_path: str = "daily_data.json") -> dict:
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return json.load(f)
    return {}
def save_data(data: dict, file_path: str = "daily_data.json"):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

def get_current_balances():
    # Це заглушка — замінити на реальні запити до Binance
    return {
        "BTC": {"amount": 0.1, "usdt_value": 6800},
        "ETH": {"amount": 0.5, "usdt_value": 1800},
        "USDT": {"amount": 1000, "usdt_value": 1000},
    }

def analyze_portfolio():
    current_data = get_current_balances()
    previous_data = load_previous_data()
    report_lines = []
    buy = []
    sell = []
    for asset, info in current_data.items():
        current_value = info["usdt_value"]
        prev_value = previous_data.get(asset, {}).get("usdt_value", current_value)
        pnl = current_value - prev_value
        pnl_percent = (pnl / prev_value) * 100 if prev_value != 0 else 0

        line = f"{asset}: {pnl:+.2f} USDT ({pnl_percent:+.2f}%)"
        report_lines.append(line)

        if pnl_percent < -THRESHOLD_PNL_PERCENT:
            sell.append(asset)
        elif pnl_percent > THRESHOLD_PNL_PERCENT:
            buy.append(asset)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    report_header = f"📊 Звіт за {date_str}\n\n"
    report_body = "\n".join(report_lines)

    gpt_prompt = (
        f"{report_header}{report_body}\n\n"
        f"🔍 Проаналізуй зміни. Які активи варто продати? Які купити? "
        f"Сформуй короткий прогноз із поясненням."
    )

    try:
        gpt_response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ти досвідчений криптоаналітик."},
                {"role": "user", "content": gpt_prompt}
            ],
            temperature=0.7
        )
        gpt_result = gpt_response["choices"][0]["message"]["content"]
    except Exception as e:
        gpt_result = f"⚠️ GPT-звіт не сформовано: {e}"
    result = {
        "date": date_str,
        "report": report_header + report_body,
        "gpt_analysis": gpt_result,
        "to_buy": buy,
        "to_sell": sell,
        "raw_data": current_data
    }

    save_data(current_data)
    return result
def run_daily_analysis() -> str:
    analysis = analyze_portfolio()

    text = (
        f"{analysis['report']}\n\n"
        f"🤖 GPT-прогноз:\n{analysis['gpt_analysis']}\n\n"
        f"📈 Купити: {', '.join(analysis['to_buy']) if analysis['to_buy'] else 'нічого'}\n"
        f"📉 Продати: {', '.join(analysis['to_sell']) if analysis['to_sell'] else 'нічого'}"
    )

    return text
def send_daily_forecast(bot: Bot, chat_id: int):
    try:
        text = run_daily_analysis()
        bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        error_text = f"❌ Помилка під час формування прогнозу: {e}"
        bot.send_message(chat_id=chat_id, text=error_text)
import os
import json
from datetime import datetime
from typing import Dict

from binance_api import get_current_portfolio
from aiogram import Bot
import openai

DATA_FILE = "daily_snapshot.json"
THRESHOLD_PNL_PERCENT = 1.0  # Знижений поріг PnL до ±1%

def load_previous_data() -> Dict:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data: Dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
def format_percent(pct: float) -> str:
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.2f}%"
    
def get_usdt_to_uah_rate() -> float:
    # Приклад заглушки — встав свою логіку, або залиш тимчасово фіксоване значення
    return 40.0

def format_currency(value: float, currency: str = "USDT") -> str:
    if currency == "UAH":
        return f"{value:,.2f}₴"
    elif currency == "BTC":
        return f"{value:.6f} BTC"
    else:
        return f"{value:,.2f} {currency}"
if __name__ == "__main__":
    class DummyBot:
        def send_message(self, chat_id, text):
            print(f"[Telegram] Chat ID: {chat_id}\n{text}\n")

    # Приклад виклику для тестування локально
    bot = DummyBot()
    test_chat_id = 123456789  # Замінити на актуальний ID для реального бота
    send_daily_forecast(bot, test_chat_id)
