import asyncio
import logging

from telegram_bot import dp, bot, setup_scheduler


logging.basicConfig(level=logging.INFO)


async def main() -> None:
    setup_scheduler()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
