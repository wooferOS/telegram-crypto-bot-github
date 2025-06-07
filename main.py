import logging
from aiogram import Dispatcher
from aiogram.utils import executor
from telegram_bot import dp, bot, setup_scheduler, register_handlers

logging.basicConfig(level=logging.INFO)


async def on_startup(dispatcher: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=True)


if __name__ == "__main__":
    setup_scheduler()
    register_handlers(dp)
    executor.start_polling(dp, on_startup=on_startup)
