import asyncio
from telegram_bot import bot
from config import CHAT_ID
from auto_trade_cycle import auto_trade_cycle

if __name__ == "__main__":
    asyncio.run(auto_trade_cycle(bot, CHAT_ID))
