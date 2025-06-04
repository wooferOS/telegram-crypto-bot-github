import os
import json
import datetime
import requests
from dotenv import load_dotenv
from binance_api import get_current_portfolio
from typing import Dict, List, Tuple, Optional
from telegram_bot import bot, CHAT_ID
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
THRESHOLD_PNL_PERCENT = 1.0  # ±1%

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {OPENAI_API_KEY}",
}

def get_usdt_to_uah_rate() -> float:
    url = "https://api.binance.com/api/v3/ticker/price?symbol=USDTUAH"
    try:
        response = requests.get(url)
        return float(response.json()["price"])
    except Exception:
        return 40.0  # fallback
        
def get_historical_data() -> Dict[str, float]:
    try:
        with open("historical_data.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}


def run_daily_analysis(current: Dict[str, float], historical: Dict[str, float]) -> Tuple[List[Dict], float]:
    """
    Порівнює поточний та історичний портфель, обчислює PnL.
    Повертає список активів з прибутками/збитками і загальний % змін.
    """
    analysis = []
    total_initial_value = 0.0
    total_current_value = 0.0

    for asset, current_amount in current.items():
        initial_amount = historical.get(asset, 0.0)

        if initial_amount == 0.0 and current_amount == 0.0:
            continue

        price_change = current_amount - initial_amount
        pnl_percent = (price_change / initial_amount) * 100 if initial_amount else 100.0

        if abs(pnl_percent) < THRESHOLD_PNL_PERCENT:
            continue  # 🔽 Фільтруємо все менше ±1%

        analysis.append({
            'asset': asset,
            'initial': round(initial_amount, 2),
            'current': round(current_amount, 2),
            'pnl_percent': round(pnl_percent, 2)
        })

        total_initial_value += initial_amount
        total_current_value += current_amount

    total_pnl_percent = ((total_current_value - total_initial_value) / total_initial_value) * 100 if total_initial_value else 0.0
    return analysis, round(total_pnl_percent, 2)

def format_analysis_report(analysis: List[Dict], total_pnl: float, usdt_to_uah: float) -> str:
    """
    Форматує звіт для Telegram-повідомлення.
    """
    if not analysis:
        return "🤖 Усі активи стабільні, змін немає понад ±1%."

    report_lines = [
        "📊 *Щоденний звіт по портфелю Binance*",
        "",
        f"💰 *Загальний результат:* `{total_pnl:+.2f}%`",
        f"🇺🇸→🇺🇦 *Курс USDT до UAH:* `{usdt_to_uah:.2f}`",
        "",
        "*Деталі по активах:*"
    ]

    for entry in analysis:
        asset = entry.get('asset', 'N/A')
        initial = entry.get('initial', 0)
        current = entry.get('current', 0)
        pnl = entry.get('pnl_percent', 0.0)
        status_emoji = "🟢" if pnl > 1 else "🔴" if pnl < -1 else "⚪️"
        report_lines.append(f"{status_emoji} `{asset}` — {pnl:+.2f}% (з {initial} до {current})")

    return "\n".join(report_lines)



def daily_analysis_task():
    current = get_current_portfolio()
    historical = get_historical_data()
    report = run_daily_analysis(current, historical)

    if report:
        try:
            max_length = 4096
            for i in range(0, len(report), max_length):
                bot.send_message(CHAT_ID, report[i:i+max_length])
        except Exception as e:
            bot.send_message(CHAT_ID, f"❌ Помилка при надсиланні GPT-звіту:\n{e}")
    else:
        bot.send_message(CHAT_ID, "⚠️ GPT-звіт не створено.")

def generate_zarobyty_report(data: dict) -> tuple[str, InlineKeyboardMarkup]:
    import datetime
    now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    report_lines = [f"📊 Звіт GPT-аналітики ({now})\n"]

    # 💼 Баланс у USDT і ₴
    report_lines.append("💼 Баланс:")
    total_usdt = 0
    for asset in data["balance"]:
        amount = asset["amount"]
        price = asset["price"]
        usdt = round(amount * price, 2)
        uah = round(usdt * data["usdt_to_uah"], 2)
        report_lines.append(f"- {asset['symbol']}: {amount} → ≈ {usdt} USDT ≈ {uah}₴")
        total_usdt += usdt

    # 📉 Рекомендується продати
    report_lines.append("\n📉 Рекомендується продати:")
    sell_buttons = []
    for asset in data["recommendations"]["sell"]:
        symbol = asset["symbol"]
        change = asset["change"]
        report_lines.append(f"- 🔴 {symbol} — зміна {change}%\n→ /confirmsell_{symbol}")
        sell_buttons.append([InlineKeyboardButton(f"🔴 Продати {symbol}", callback_data=f"/confirmsell_{symbol}")])

    # 📈 Рекомендується купити
    report_lines.append("\n📈 Рекомендується купити:")
    buy_buttons = []
    for asset in data["recommendations"]["buy"]:
        symbol = asset["symbol"]
        volume = asset["volume"]
        change = asset["change"]
        report_lines.append(f"- 🟢 {symbol} — обʼєм {volume} | зміна {change}%\n→ /confirmbuy_{symbol}")
        buy_buttons.append([InlineKeyboardButton(f"🟢 Купити {symbol}", callback_data=f"/confirmbuy_{symbol}")])

    # 📈 Очікуваний прибуток
    profit = data.get("expected_profit", 0)
    report_lines.append(f"\n📈 Очікуваний прибуток: ~{profit} USDT")

    # 📈 ОЧІKУВАНИЙ ПРИБУТОК (детально)
    if "profit_calc" in data:
        report_lines.append("\n📈 ОЧІKУВАНИЙ ПРИБУТОК:")
        for line in data["profit_calc"]:
            report_lines.append(f"- {line}")
        if "total_profit" in data:
            report_lines.append(f"= Разом: {data['total_profit']}")

    # 🧠 Прогноз
    if "forecast" in data:
        report_lines.append(f"\n🧠 Прогноз: {data['forecast']}")

    # 💾 Завершення
    report_lines.append("💾 Усі дії збережено.")

    # Обʼєднані кнопки
    all_buttons = sell_buttons + buy_buttons
    markup = InlineKeyboardMarkup(all_buttons)

    return "\n".join(report_lines), markup


if __name__ == "__main__":
    # Це виконується лише якщо запускати daily_analysis.py напряму
    print("Цей файл не призначений для прямого запуску.")
