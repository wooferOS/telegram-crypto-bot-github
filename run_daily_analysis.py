import asyncio
from telegram_bot import bot
from config import CHAT_ID
from daily_analysis import daily_analysis_task


if __name__ == "__main__":
    asyncio.run(daily_analysis_task(bot, CHAT_ID))
