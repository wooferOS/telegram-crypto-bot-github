import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PLACEHOLDER")
if TELEGRAM_TOKEN == "PLACEHOLDER":
    print("\u26a0\ufe0f Warning: TELEGRAM_TOKEN is empty. Make sure .env is loaded on server.")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

import telegram_bot  # noqa: F401  # register handlers

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
