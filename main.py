import os
from dotenv import load_dotenv
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from telegram_bot import bot, dp, ADMIN_CHAT_ID  # registers handlers
from daily_analysis import daily_analysis_task, send_zarobyty_forecast

load_dotenv()

if os.getenv("TELEGRAM_TOKEN", "PLACEHOLDER") == "PLACEHOLDER":
    print("⚠️ Warning: TELEGRAM_TOKEN is empty. Make sure .env is loaded on server.")


if __name__ == "__main__":
    scheduler = AsyncIOScheduler(timezone="Europe/Kiev")
    scheduler.add_job(daily_analysis_task, "cron", hour=8, minute=55, args=(bot, ADMIN_CHAT_ID))
    scheduler.add_job(send_zarobyty_forecast, "cron", hour=9, minute=0, args=(bot, ADMIN_CHAT_ID))
    scheduler.start()
    executor.start_polling(dp, skip_updates=True)
