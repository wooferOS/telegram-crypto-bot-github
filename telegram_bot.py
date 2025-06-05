import os
from telebot import TeleBot, types
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
print("🧪 BOT TOKEN:", TELEGRAM_BOT_TOKEN)
CHAT_ID = os.getenv("CHAT_ID")

bot = TeleBot(TELEGRAM_BOT_TOKEN)


@bot.callback_query_handler(func=lambda call: True)
def handle_inline_buttons(call: types.CallbackQuery) -> None:
    """Handle simple inline button confirmations."""
    if call.data == "confirmbuy_ETH":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🟢 Купівля ETH підтверджена!")
    elif call.data == "confirmsell_BTC":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🔴 Продаж BTC підтверджена!")
