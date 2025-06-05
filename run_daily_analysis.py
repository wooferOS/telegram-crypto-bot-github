import asyncio

from daily_analysis import daily_analysis_task
from telegram_bot import bot, ADMIN_CHAT_ID

if __name__ == "__main__":
    asyncio.run(daily_analysis_task(bot, ADMIN_CHAT_ID))
