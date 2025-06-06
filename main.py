import logging
import os
from aiogram import Bot, Dispatcher, types, executor
from daily_analysis import generate_zarobyty_report
from binance_api import place_market_order

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

logging.basicConfig(level=logging.INFO)

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    await message.reply(
        "\U0001F44B Вітаю! Я GPT-бот для криптотрейдингу. Використовуйте команду /zarobyty для щоденного звіту."
    )

@dp.message_handler(commands=['zarobyty'])
async def zarobyty_cmd(message: types.Message):
    report = generate_zarobyty_report()
    await message.reply(report, parse_mode='Markdown')

@dp.callback_query_handler(lambda c: c.data.startswith('confirmbuy_'))
async def confirm_buy(callback_query: types.CallbackQuery):
    token = callback_query.data.replace('confirmbuy_', '')
    result = place_market_order(symbol=token, side="BUY", quantity=5)
    await bot.answer_callback_query(callback_query.id, text=f"Купівля {token} підтверджена.")
    await bot.send_message(callback_query.from_user.id, f"\U0001F7E2 Куплено {token}: {result}")

@dp.callback_query_handler(lambda c: c.data.startswith('confirmsell_'))
async def confirm_sell(callback_query: types.CallbackQuery):
    token = callback_query.data.replace('confirmsell_', '')
    result = place_market_order(symbol=token, side="SELL", quantity=5)
    await bot.answer_callback_query(callback_query.id, text=f"Продаж {token} підтверджено.")
    await bot.send_message(callback_query.from_user.id, f"\U0001F534 Продано {token}: {result}")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
