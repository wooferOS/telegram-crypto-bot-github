import os
from datetime import datetime
from typing import Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from gpt_utils import generate_investor_summary
from history import generate_history_report as history_report
from stats import generate_stats_report as stats_report
from alerts import record_forecast

from binance_api import (
    get_usdt_balance,
    get_token_balance,
    get_symbol_price,
    get_all_tokens_with_balance,
)


UAH_RATE = 39.2  # 1 USDT ~ 39.2 грн


def generate_zarobyty_report() -> Tuple[str, InlineKeyboardMarkup]:
    """Return formatted Telegram report with market analysis and buttons."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Отримуємо всі токени з балансу
    portfolio_tokens = get_all_tokens_with_balance()
    balances = []
    total_uah = 0.0

    for token in portfolio_tokens:
        amount = get_token_balance(token)
        if token == "USDT":
            # \u0414\u043e\u0434\u0430\u0454\u043c\u043e \u0442\u0456\u043b\u044c\u043a\u0438 \u0434\u043e \u0431\u0430\u043b\u0430\u043d\u0441\u0443, \u043d\u0435 \u043f\u0435\u0440\u0435\u0432\u0456\u0440\u044f\u0454\u043c\u043e \u0437\u043c\u0456\u043d\u0438 \u0446\u0456\u043d\u0438
            uah_value = round(amount * UAH_RATE, 2)
            total_uah += uah_value
            balances.append(f"{token}: {amount:.2f} \u2248 ~{uah_value:,.2f}\u20b4")
            continue
        if amount == 0:
            continue

        price = get_symbol_price(token)
        uah_value = round(amount * price * UAH_RATE, 2)
        total_uah += uah_value

        balances.append(f"{token}: {amount:.2f} ≈ ~{uah_value:,.2f}₴")
    tokens = portfolio_tokens
    sell_recommendations = []
    buy_recommendations = []
    expected_profit = 0.0
    buttons = []
    keyboard = InlineKeyboardMarkup(row_width=2)

    for token in tokens:
        amount = get_token_balance(token)
        if token == "USDT":
            continue
        price = get_symbol_price(token)
        uah_value = round(amount * price * UAH_RATE, 2)
        # \u041f\u0441\u0435\u0432\u0434\u043e-\u0456\u0441\u0442\u043e\u0440\u0438\u0447\u043d\u0430 \u0446\u0456\u043d\u0430 \u0434\u043b\u044f \u0434\u0435\u043c\u043e\u043d\u0441\u0442\u0440\u0430\u0446\u0456\u0457
        purchase_price = price * 0.98  # \u2b06\ufe0f \u0437\u0430\u043c\u0456\u043d\u0438\u0442\u0438 \u043d\u0430 \u0440\u0435\u0430\u043b\u044c\u043d\u0443 \u0456\u0441\u0442\u043e\u0440\u0438\u0447\u043d\u0443, \u043a\u043e\u043b\u0438 \u0431\u0443\u0434\u0435 \u0433\u043e\u0442\u043e\u0432\u0430
        if purchase_price == 0:
            continue

        percent_change = round((price - purchase_price) / purchase_price * 100, 2)

        if percent_change > 1.0:
            sell_recommendations.append(f"\U0001f534 {token}: {amount:.2f} (\u2191 {percent_change}%)")
            buttons.append(
                InlineKeyboardButton(
                    text=f"\U0001F534 \u041F\u0440\u043E\u0434\u0430\u0442\u0438 {token}",
                    callback_data=f"confirmsell_{token}"
                )
            )
        elif percent_change < -1.0:
            buy_recommendations.append(
                f"\U0001f7e2 {token} ({percent_change}%)"
            )
            buttons.append(
                InlineKeyboardButton(
                    text=f"\U0001F7E2 \u041A\u0443\u043F\u0438\u0442\u0438 {token}",
                    callback_data=f"confirmbuy_{token}"
                )
            )
            expected_profit += round(amount * price * 0.02, 2)

    keyboard.add(*buttons)
    gpt_summary = call_gpt_summary(balances, sell_recommendations, buy_recommendations)

    # record tokens for alert if user doesn't act
    record_forecast(buy_recommendations + sell_recommendations)

    report = (
        f"\ud83d\udcca \u0417\u0432\u0456\u0442 GPT-\u0430\u043d\u0430\u043b\u0456\u0442\u0438\u043a\u0438 ({now})\n\n"
        "💰 *Баланс:*\n"
        + "\n".join(balances)
        + f"\n\n*Загалом:* ~{total_uah:,.2f}₴\n\n"
        "\ud83d\udcc9 \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0443\u0454\u0442\u044c\u0441\u044f \u043f\u0440\u043e\u0434\u0430\u0442\u0438:\n"
        + "\n".join(sell_recommendations or ["\u041d\u0456\u0447\u043e\u0433\u043e"])
        + "\n\n"
        "\ud83d\udcc8 \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0443\u0454\u0442\u044c\u0441\u044f \u043a\u0443\u043f\u0438\u0442\u0438:\n"
        + "\n".join(buy_recommendations or ["\u041d\u0456\u0447\u043e\u0433\u043e"])
        + "\n\n"
        f"\ud83d\udcc8 \u041e\u0447\u0456\u043a\u0443\u0432\u0430\u043d\u0438\u0439 \u043f\u0440\u0438\u0431\u0443\u0442\u043e\u043a: ~{expected_profit} USDT\n\n"
        f"\ud83e\uddd0 \u041f\u0440\u043e\u0433\u043d\u043e\u0437 GPT:\n{gpt_summary}\n\n\ud83d\udcbe \u0423\u0441\u0456 \u0434\u0456\u0457 \u0437\u0431\u0435\u0440\u0435\u0436\u0435\u043d\u043e."
    )

    return report, keyboard


def call_gpt_summary(balance, sells, buys):
    """Return short GPT investor summary."""
    return generate_investor_summary(balance, sells, buys)


def generate_history_report() -> str:
    """Return text with stored trade history."""
    return history_report()


def generate_stats_report() -> str:
    """Return profit statistics."""
    return stats_report()


def generate_daily_stats_report() -> str:
    """Alias for daily stats (currently same as stats)."""
    return generate_stats_report()


async def daily_analysis_task(bot: Bot, chat_id: int) -> None:
    """Generate report and send to Telegram chat."""
    report, keyboard = generate_zarobyty_report()
    await bot.send_message(chat_id, report, reply_markup=keyboard)


async def send_zarobyty_forecast(bot: Bot, chat_id: int) -> None:
    """Send GPT forecast with confirmation button."""
    report, keyboard = generate_zarobyty_report()
    await bot.send_message(chat_id, report, reply_markup=keyboard)


if __name__ == "__main__":
    print("\u0426\u0435\u0439 \u0444\u0430\u0439\u043b \u043d\u0435 \u043f\u0440\u0438\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0439 \u0434\u043b\u044f \u043f\u0440\u044f\u043c\u043e\u0433\u043e \u0437\u0430\u043f\u0443\u0441\u043a\u0443.")
