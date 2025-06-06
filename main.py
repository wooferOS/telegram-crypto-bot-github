import logging
from aiogram import Bot, Dispatcher, types, executor
from telegram_bot import dp, bot, setup_scheduler


logging.basicConfig(level=logging.INFO)


async def on_startup(dispatcher: Dispatcher) -> None:
    setup_scheduler()
    await bot.delete_webhook(drop_pending_updates=True)


if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup)
