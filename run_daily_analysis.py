import asyncio

from secure_env_loader import load_env_file

load_env_file("/root/.env")

from telegram_bot import bot
from config import CHAT_ID
from daily_analysis import daily_analysis_task


if __name__ == "__main__":
    asyncio.run(daily_analysis_task(bot, CHAT_ID))
