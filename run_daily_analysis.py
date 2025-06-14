import asyncio
import sys

from daily_analysis import daily_analysis_task, send_zarobyty_forecast
from telegram_bot import bot, ADMIN_CHAT_ID


if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else "report"
    if task == "forecast":
        asyncio.run(send_zarobyty_forecast(bot, ADMIN_CHAT_ID))
    else:
        asyncio.run(daily_analysis_task(bot, ADMIN_CHAT_ID))
