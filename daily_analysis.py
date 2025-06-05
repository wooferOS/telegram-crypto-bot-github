import os
import json
import datetime
import requests
from dotenv import load_dotenv
from binance_api import get_current_portfolio, get_full_asset_info
from typing import Dict, List, Tuple, Optional
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor



load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
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



async def daily_analysis_task(bot: Bot, chat_id: int) -> None:
    """Run analysis and send formatted report via the provided bot."""
    current = get_current_portfolio()
    historical = get_historical_data()
    analysis, total_pnl = run_daily_analysis(current, historical)

    if analysis:
        try:
            rate = get_usdt_to_uah_rate()
            message = format_analysis_report(analysis, total_pnl, rate)
            await bot.send_message(chat_id, message)
        except Exception as e:
            await bot.send_message(chat_id, f"❌ Помилка при надсиланні GPT-звіту:\n{e}")
    else:
        await bot.send_message(chat_id, "⚠️ GPT-звіт не створено.")

def generate_zarobyty_report():
    data = get_full_asset_info()

    balances = "\n".join(
        [f"- {b['symbol']}: {b['amount']} → ≈ {b['usdt_value']} USDT" for b in data["balances"]]
    )

    sell = "\n".join(
        [f"- 🔴 {s['symbol']} — зміна {s['change_percent']}%\n→ /confirmsell_{s['symbol']}" for s in data["recommend_sell"]]
    )

    buy = "\n".join(
        [f"- 🟢 {b['symbol']} — обʼєм {b['volume']} | зміна {b['change_percent']}%\n→ /confirmbuy_{b['symbol']}" for b in data["recommend_buy"]]
    )

    pnl = "\n".join([
        f"{p['symbol']}: {p['prev_amount']} → {p['current_amount']} ({'+' if p['diff'] >= 0 else ''}{p['diff']}, {p['percent']}%)"
        for p in data["pnl"]
    ])

    report = f"""📊 Звіт GPT-аналітики ({datetime.datetime.now().strftime('%d.%m.%Y %H:%M')})

💼 Баланс:
{balances}

📉 Рекомендується продати:
{sell}

📈 Рекомендується купити:
{buy}

📈 Очікуваний прибуток: ~{data['expected_profit']} USDT

📈 ОЧІKУВАНИЙ ПРИБУТОК:
{data['expected_profit_block']}

🧠 Прогноз: {data['gpt_forecast']}
💾 Усі дії збережено."""

    return report


if __name__ == "__main__":
    # Це виконується лише якщо запускати daily_analysis.py напряму
    print("Цей файл не призначений для прямого запуску.")
