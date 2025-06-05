import os
import asyncio
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from telegram_bot import bot, dp, ADMIN_CHAT_ID  # registers handlers
from daily_analysis import daily_analysis_task, send_zarobyty_forecast

load_dotenv(dotenv_path=os.path.expanduser("~/.env"))

if os.getenv("TELEGRAM_TOKEN", "PLACEHOLDER") == "PLACEHOLDER":
    print("⚠️ Warning: TELEGRAM_TOKEN is empty. Make sure .env is loaded on server.")


async def main():
    scheduler = AsyncIOScheduler(timezone="Europe/Kiev")
    scheduler.add_job(
        daily_analysis_task,
        "cron",
        hour=8,
        minute=55,
        args=(bot, ADMIN_CHAT_ID),
    )
    scheduler.add_job(
        send_zarobyty_forecast,
        "cron",
        hour=9,
        minute=0,
        args=(bot, ADMIN_CHAT_ID),
    )
    scheduler.start()
    await dp.start_polling()


if __name__ == "__main__":
    asyncio.run(main())
