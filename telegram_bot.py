"""Telegram bot configuration and handlers."""

import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher.filters import Command
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from daily_analysis import (
    generate_zarobyty_report,
    generate_daily_stats_report,
    daily_analysis_task,
)
from history import generate_history_report
from stats import generate_stats_report
from binance_api import place_market_order
from alerts import check_daily_alerts


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", os.getenv("CHAT_ID", "0")))

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

scheduler = AsyncIOScheduler(timezone="UTC")


@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.reply(
        "\U0001F44B Вітаю! Я GPT-бот для криптотрейдингу. Використовуйте команду /zarobyty для щоденного звіту."
    )


@dp.message_handler(Command("zarobyty"))
async def zarobyty_cmd(message: types.Message):
    report, keyboard = generate_zarobyty_report()
    await message.reply(report, parse_mode="Markdown", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("confirmbuy_"))
async def confirm_buy(callback_query: types.CallbackQuery):
    token = callback_query.data.replace("confirmbuy_", "")
    result = place_market_order(symbol=token, side="BUY", quantity=5)
    await callback_query.answer(f"Купівля {token} підтверджена.")
    await callback_query.message.answer(f"\U0001F7E2 Куплено {token}: {result}")


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("confirmsell_"))
async def confirm_sell(callback_query: types.CallbackQuery):
    token = callback_query.data.replace("confirmsell_", "")
    result = place_market_order(symbol=token, side="SELL", quantity=5)
    await callback_query.answer(f"Продаж {token} підтверджено.")
    await callback_query.message.answer(f"\U0001F534 Продано {token}: {result}")


@dp.message_handler(commands=["history"])
async def history_cmd(message: types.Message):
    await message.reply(generate_history_report(), parse_mode="Markdown")


@dp.message_handler(commands=["stats"])
async def stats_cmd(message: types.Message):
    await message.reply(generate_stats_report(), parse_mode="Markdown")


@dp.message_handler(commands=["statsday"])
async def statsday_cmd(message: types.Message):
    await message.reply(generate_daily_stats_report(), parse_mode="Markdown")


@dp.message_handler(commands=["alerts_on"])
async def alerts_on_cmd(message: types.Message):
    await message.reply("Щоденні сповіщення увімкнено.")


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

