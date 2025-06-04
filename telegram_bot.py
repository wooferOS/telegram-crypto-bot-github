import os
from telebot import TeleBot
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
print("🧪 BOT TOKEN:", TELEGRAM_BOT_TOKEN)
CHAT_ID = os.getenv("CHAT_ID")

bot = TeleBot(TELEGRAM_BOT_TOKEN)
