import os
import json
import datetime
import requests
from dotenv import load_dotenv
from binance_api import get_current_portfolio
from typing import Dict, List, Tuple, Optional

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



if __name__ == "__main__":
    # Це виконується лише якщо запускати daily_analysis.py напряму
    print("Цей файл не призначений для прямого запуску.")
