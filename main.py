import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, executor

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Missing TELEGRAM_TOKEN environment variable")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

import telegram_bot  # noqa: F401  # register handlers

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
