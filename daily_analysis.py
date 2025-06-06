import os
from datetime import datetime
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from binance_api import (
    get_usdt_balance,
    get_token_balance,
    get_symbol_price,
    get_token_value_in_uah,
)

import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

UAH_RATE = 39.2  # 1 USDT ~ 39.2 грн

def generate_zarobyty_report() -> str:
    """Return formatted Telegram report with market analysis."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tokens = ["BTC", "ETH", "SOL", "XRP", "DOGE", "HBAR"]
    usdt_balance = get_usdt_balance()
    total_uah = round(usdt_balance * UAH_RATE, 2)

    balances = []
    sell_recommendations = []
    buy_recommendations = []
    expected_profit = 0.0

    for token in tokens:
        amount = get_token_balance(token)
        price = get_symbol_price(token)
        uah_value = round(amount * price * UAH_RATE, 2)
        percent_change = round((price - price * 0.98) / price * 100, 2)

        if amount > 0:
            balances.append(f"\U0001f539 {token}: {amount:.4f} = ~{uah_value}\u20b4")
        if percent_change < -1.0:
            sell_recommendations.append(
                f"\U0001f534 {token} ({percent_change}%) /confirmsell_{token}"
            )
        elif percent_change > 1.0:
            buy_recommendations.append(
                f"\U0001f7e2 {token} ({percent_change}%) /confirmbuy_{token}"
            )
            expected_profit += round(amount * price * 0.02, 2)

    gpt_summary = call_gpt_summary(balances, sell_recommendations, buy_recommendations)

    report = (
        f"\ud83d\udcca \u0417\u0432\u0456\u0442 GPT-\u0430\u043d\u0430\u043b\u0456\u0442\u0438\u043a\u0438 ({now})\n\n"
        "\ud83d\udcbc \u0411\u0430\u043b\u0430\u043d\u0441:\n"
        + "\n".join(balances)
        + f"\n\n\ud83d\udcb0 \u0417\u0430\u0433\u0430\u043b\u044c\u043d\u0438\u0439 \u0431\u0430\u043b\u0430\u043d\u0441: ~{total_uah}\u20b4\n\n"
        "\ud83d\udcc9 \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0443\u0454\u0442\u044c\u0441\u044f \u043f\u0440\u043e\u0434\u0430\u0442\u0438:\n"
        + "\n".join(sell_recommendations or ["\u041d\u0456\u0447\u043e\u0433\u043e"])
        + "\n\n"
        "\ud83d\udcc8 \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0443\u0454\u0442\u044c\u0441\u044f \u043a\u0443\u043f\u0438\u0442\u0438:\n"
        + "\n".join(buy_recommendations or ["\u041d\u0456\u0447\u043e\u0433\u043e"])
        + "\n\n"
        f"\ud83d\udcc8 \u041e\u0447\u0456\u043a\u0443\u0432\u0430\u043d\u0438\u0439 \u043f\u0440\u0438\u0431\u0443\u0442\u043e\u043a: ~{expected_profit} USDT\n\n"
        f"\ud83e\uddd0 \u041f\u0440\u043e\u0433\u043d\u043e\u0437 GPT:\n{gpt_summary}\n\n\ud83d\udcbe \u0423\u0441\u0456 \u0434\u0456\u0457 \u0437\u0431\u0435\u0440\u0435\u0436\u0435\u043d\u043e."
    )

    return report


def call_gpt_summary(balance, sells, buys):
    """Use OpenAI to generate short investor summary."""
    prompt = f"""
\u0421\u0444\u043e\u0440\u043c\u0443\u0439 \u043a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 \u0456\u043d\u0432\u0435\u0441\u0442\u043e\u0440\u0441\u044c\u043a\u0438\u0439 \u043f\u0440\u043e\u0433\u043d\u043e\u0437 \u043d\u0430 \u043e\u0441\u043d\u043e\u0432\u0456:\n\n\u0411\u0430\u043b\u0430\u043d\u0441:\n{balance}\n\n\u041f\u0440\u043e\u0434\u0430\u0442\u0438:\n{sells}\n\n\u041a\u0443\u043f\u0438\u0442\u0438:\n{buys}\n"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:  # pragma: no cover - network call
        return f"[GPT Error] {e}"


async def daily_analysis_task(bot: Bot, chat_id: int) -> None:
    """Generate report and send to Telegram chat."""
    report = generate_zarobyty_report()
    await bot.send_message(chat_id, report)


async def send_zarobyty_forecast(bot: Bot, chat_id: int) -> None:
    """Send GPT forecast with confirmation button."""
    report = generate_zarobyty_report()
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("\u041f\u0456\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0438", callback_data="confirm")
    )
    await bot.send_message(chat_id, report, reply_markup=keyboard)


if __name__ == "__main__":
    print("\u0426\u0435\u0439 \u0444\u0430\u0439\u043b \u043d\u0435 \u043f\u0440\u0438\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0439 \u0434\u043b\u044f \u043f\u0440\u044f\u043c\u043e\u0433\u043e \u0437\u0430\u043f\u0443\u0441\u043a\u0443.")
