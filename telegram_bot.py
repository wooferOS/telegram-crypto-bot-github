import os
from telebot import TeleBot, types
from dotenv import load_dotenv
from daily_analysis import generate_zarobyty_report

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
print("🧪 BOT TOKEN:", TELEGRAM_BOT_TOKEN)
CHAT_ID = os.getenv("CHAT_ID")

bot = TeleBot(TELEGRAM_BOT_TOKEN)


@bot.message_handler(commands=["zarobyty"])
def handle_zarobyty(message):
    """Send profit report with inline buttons."""
    report_text = generate_zarobyty_report()

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("🔴 Продати BTC", callback_data="confirmsell_BTC"),
        types.InlineKeyboardButton("🟢 Купити ETH", callback_data="confirmbuy_ETH"),
    )

    bot.send_message(message.chat.id, report_text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def handle_inline_buttons(call: types.CallbackQuery) -> None:
    if call.data == "confirmbuy_ETH":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🟢 Купівля ETH підтверджена!")
    elif call.data == "confirmsell_BTC":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🔴 Продаж BTC підтверджена!")
