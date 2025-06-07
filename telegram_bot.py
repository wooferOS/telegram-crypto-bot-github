"""Telegram bot configuration and handlers."""

import os
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from daily_analysis import (
    generate_zarobyty_report,
    generate_daily_stats_report,
    daily_analysis_task,
)
from history import generate_history_report
from stats import generate_stats_report
from binance_api import place_market_order, get_price_history_24h
from alerts import check_daily_alerts


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", os.getenv("CHAT_ID", "0")))

bot = Bot(token=TELEGRAM_TOKEN)

scheduler = AsyncIOScheduler(timezone="UTC")


def setup_scheduler() -> None:
    """Configure daily tasks for APScheduler."""
    scheduler.add_job(
        daily_analysis_task,
        "cron",
        hour=7,
        args=(bot, ADMIN_CHAT_ID),
    )
    scheduler.add_job(
        check_daily_alerts,
        "cron",
        hour=8,
        args=(bot, ADMIN_CHAT_ID),
    )
    scheduler.start()


def clean_surrogates(text: str) -> str:
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "ignore")


def register_handlers(dp: Dispatcher) -> None:
    """Register bot command and callback handlers."""

    async def start_cmd(message: types.Message) -> None:
        await message.reply(
            "\U0001F44B Вітаю! Я GPT-бот для криптотрейдингу. Використовуйте команду /zarobyty для щоденного звіту."
        )

    async def zarobyty_cmd(message: types.Message) -> None:
        report, keyboard = generate_zarobyty_report()
        report = clean_surrogates(report)
        await message.reply(report, parse_mode="Markdown", reply_markup=keyboard)

    async def confirm_buy(callback_query: types.CallbackQuery) -> None:
        token = callback_query.data.replace("confirmbuy_", "")
        result = place_market_order(symbol=token, side="BUY", quantity=5)
        await callback_query.answer(f"Купівля {token} підтверджена.")
        await callback_query.message.answer(f"\U0001F7E2 Куплено {token}: {result}")

    async def confirm_sell(callback_query: types.CallbackQuery) -> None:
        token = callback_query.data.replace("confirmsell_", "")
        result = place_market_order(symbol=token, side="SELL", quantity=5)
        await callback_query.answer(f"Продаж {token} підтверджено.")
        await callback_query.message.answer(f"\U0001F534 Продано {token}: {result}")

    async def history_cmd(message: types.Message) -> None:
        await message.reply(generate_history_report(), parse_mode="Markdown")

    async def stats_cmd(message: types.Message) -> None:
        await message.reply(generate_stats_report(), parse_mode="Markdown")

    async def statsday_cmd(message: types.Message) -> None:
        await message.reply(generate_daily_stats_report(), parse_mode="Markdown")

    async def price24_cmd(message: types.Message) -> None:
        token = message.get_args().split()[0].upper() if message.get_args() else "BTC"
        prices = get_price_history_24h(token)
        if not prices:
            await message.reply(f"\u274C \u041d\u0435 \u043e\u0442\u0440\u0438\u043c\u0430\u043d\u043e \u0434\u0430\u043d\u0456 \u0434\u043b\u044f {token}.")
            return
        formatted = ", ".join(f"{p:.4f}" for p in prices)
        await message.reply(f"\U0001F4C8 \u0426\u0456\u043d\u0438 {token} \u0437\u0430 24\u0433:\n{formatted}")

    async def alerts_on_cmd(message: types.Message) -> None:
        await message.reply("Щоденні сповіщення увімкнено.")

    dp.register_message_handler(start_cmd, commands=["start"])
    dp.register_message_handler(zarobyty_cmd, Command("zarobyty"))
    dp.register_callback_query_handler(
        confirm_buy, lambda c: c.data and c.data.startswith("confirmbuy_")
    )
    dp.register_callback_query_handler(
        confirm_sell, lambda c: c.data and c.data.startswith("confirmsell_")
    )
    dp.register_message_handler(history_cmd, commands=["history"])
    dp.register_message_handler(stats_cmd, commands=["stats"])
    dp.register_message_handler(statsday_cmd, commands=["statsday"])
    dp.register_message_handler(price24_cmd, commands=["price24"])
    dp.register_message_handler(alerts_on_cmd, commands=["alerts_on"])


