import asyncio
import logging
import sys

from secure_env_loader import load_env_file

load_env_file("/root/.env")

from telegram_bot import bot
from config import CHAT_ID
from auto_trade_cycle import auto_trade_cycle

LOG_PATH = "/root/trade.log"
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)

if __name__ == "__main__":
    chat_id = int(CHAT_ID) if CHAT_ID else 0
    asyncio.run(auto_trade_cycle(bot, chat_id))
