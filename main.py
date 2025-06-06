import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command
from daily_analysis import (
    generate_zarobyty_report,
    generate_daily_stats_report,
)
from history import generate_history_report
from stats import generate_stats_report
from binance_api import place_market_order

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = Bot(token=TELEGRAM_TOKEN)
router = Router()
dp = Dispatcher()
dp.include_router(router)

logging.basicConfig(level=logging.INFO)

@router.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.reply(
        "\U0001F44B Вітаю! Я GPT-бот для криптотрейдингу. Використовуйте команду /zarobyty для щоденного звіту."
    )

@router.message(Command("zarobyty"))
async def zarobyty_cmd(message: types.Message):
    report, keyboard = generate_zarobyty_report()
    await message.reply(report, parse_mode='Markdown', reply_markup=keyboard)

@router.callback_query(F.data.startswith("confirmbuy_"))
async def confirm_buy(callback_query: types.CallbackQuery):
    token = callback_query.data.replace('confirmbuy_', '')
    result = place_market_order(symbol=token, side="BUY", quantity=5)
    await callback_query.answer(f"Купівля {token} підтверджена.")
    await callback_query.message.answer(f"\U0001F7E2 Куплено {token}: {result}")

@router.callback_query(F.data.startswith("confirmsell_"))
async def confirm_sell(callback_query: types.CallbackQuery):
    token = callback_query.data.replace('confirmsell_', '')
    result = place_market_order(symbol=token, side="SELL", quantity=5)
    await callback_query.answer(f"Продаж {token} підтверджено.")
    await callback_query.message.answer(f"\U0001F534 Продано {token}: {result}")


@router.message(Command("history"))
async def history_cmd(message: types.Message):
    await message.reply(generate_history_report(), parse_mode='Markdown')


@router.message(Command("stats"))
async def stats_cmd(message: types.Message):
    await message.reply(generate_stats_report(), parse_mode='Markdown')


@router.message(Command("statsday"))
async def statsday_cmd(message: types.Message):
    await message.reply(generate_daily_stats_report(), parse_mode='Markdown')


@router.message(Command("alerts_on"))
async def alerts_on_cmd(message: types.Message):
    await message.reply('Щоденні сповіщення увімкнено.')

async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
