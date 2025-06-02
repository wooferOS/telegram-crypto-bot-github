import os
import json
import datetime
import requests
from aiogram import Bot
from dotenv import load_dotenv
from binance_api import get_current_portfolio

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
THRESHOLD_PNL_PERCENT = 1.0  # ±1%

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {OPENAI_API_KEY}",
}


def fetch_usdt_to_uah_rate():
    try:
        response = requests.get(
            "https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB"
        )
        rate_rub = float(response.json()["price"])
        # Перетворимо RUB → UAH орієнтовно (1 RUB ≈ 0.38 UAH)
        return rate_rub * 0.38
    except Exception as e:
        print(f"[fetch_usdt_to_uah_rate] Error: {e}")
        return 38.0
def analyze_portfolio(portfolio):
    analysis = []
    total_initial_value = 0
    total_current_value = 0

    for asset in portfolio:
        symbol = asset["symbol"]
        initial_value = float(asset.get("initial_value", 0))
        current_value = float(asset.get("current_value", 0))

        if initial_value == 0:
            continue

        pnl_percent = ((current_value - initial_value) / initial_value) * 100
        total_initial_value += initial_value
        total_current_value += current_value

        if abs(pnl_percent) >= THRESHOLD_PNL_PERCENT:
            analysis.append(
                {
                    "symbol": symbol,
                    "initial_value": initial_value,
                    "current_value": current_value,
                    "pnl_percent": round(pnl_percent, 2),
                }
            )

    total_pnl_percent = (
        ((total_current_value - total_initial_value) / total_initial_value) * 100
        if total_initial_value > 0
        else 0
    )

    return analysis, round(total_pnl_percent, 2)
def format_analysis_report(analysis, total_pnl_percent, usdt_to_uah_rate):
    if not analysis:
        return "🤖 Усі активи стабільні, змін немає понад ±1%."

    lines = ["📊 *Аналіз портфеля з відхиленням понад ±1%:*"]
    for item in analysis:
        change_emoji = "📈" if item["pnl_percent"] > 0 else "📉"
        direction = "зросла" if item["pnl_percent"] > 0 else "знизилась"
        usdt_change = item["current_value"] - item["initial_value"]
        uah_change = usdt_change * usdt_to_uah_rate
        lines.append(
            f"{change_emoji} *{item['symbol']}*: {direction} на *{item['pnl_percent']}%*"
            f" (≈ {round(usdt_change, 2)} USDT / ≈ {round(uah_change)} UAH)"
        )

    total_emoji = "✅" if total_pnl_percent > 0 else "⚠️" if total_pnl_percent < 0 else "➖"
    lines.append(f"\n{total_emoji} *Загальний PnL*: {total_pnl_percent}%")

    return "\n".join(lines)
async def send_daily_forecast(bot: Bot, chat_id: int):
    try:
        # Отримати курс USDT/UAH
        usdt_to_uah_rate = get_usdt_to_uah_rate()

        # Отримати поточний портфель з Binance
        current_portfolio = get_current_portfolio()

        # Завантажити історичний портфель з БД
        historical_portfolio = load_historical_portfolio()

        # Зберегти поточний портфель у БД
        save_current_portfolio(current_portfolio)

        # Обробити щоденний аналіз
        analysis, total_pnl_percent = run_daily_analysis(current_portfolio, historical_portfolio)

        # Сформувати повідомлення
        message_text = format_analysis_report(analysis, total_pnl_percent, usdt_to_uah_rate)

        # Надіслати у Telegram
        await bot.send_message(chat_id=chat_id, text=message_text, parse_mode="Markdown")

    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"❌ Помилка щоденного аналізу: {e}")
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
    report_lines = [
        "📊 *Щоденний звіт по портфелю Binance*",
        "",
        f"💰 *Загальний результат:* `{total_pnl:+.2f}%`",
        f"🇺🇸→🇺🇦 *Курс USDT до UAH:* `{usdt_to_uah:.2f}`",
        "",
        "*Деталі по активах:*"
    ]

    for entry in analysis:
        asset = entry['asset']
        initial = entry['initial']
        current = entry['current']
        pnl = entry['pnl_percent']
        status_emoji = "🟢" if pnl > 1 else "🔴" if pnl < -1 else "⚪️"
        report_lines.append(f"{status_emoji} `{asset}` — {pnl:+.2f}% (з {initial} до {current})")

    return "\n".join(report_lines)
async def send_daily_forecast(bot: Bot, chat_id: int):
    """
    Асинхронно виконує аналіз і надсилає звіт у Telegram.
    """
    try:
        portfolio = get_current_portfolio()
        if not portfolio:
            await bot.send_message(chat_id, "❗️Не вдалося отримати дані з Binance.")
            return

        usdt_to_uah = get_usdt_to_uah_rate()
        analysis = analyze_portfolio(portfolio)
        total_pnl = sum(a['pnl_percent'] for a in analysis) / len(analysis) if analysis else 0.0

        report = format_analysis_report(analysis, total_pnl, usdt_to_uah)
        await bot.send_message(chat_id, report, parse_mode="Markdown")
    except Exception as e:
        await bot.send_message(chat_id, f"🚨 Помилка при генерації звіту: {e}")
if __name__ == "__main__":
    # Це виконується лише якщо запускати daily_analysis.py напряму
    print("Цей файл не призначений для прямого запуску.")
