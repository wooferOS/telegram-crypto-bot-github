import os
from telebot import TeleBot, types
from dotenv import load_dotenv
from daily_analysis import generate_zarobyty_report

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = TeleBot(TELEGRAM_BOT_TOKEN)


@bot.message_handler(commands=["zarobyty"])
def handle_zarobyty(message: types.Message) -> None:
    """Send profit report with buy/sell buttons."""
    report_text = generate_zarobyty_report()

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("🟢 Купити ETH", callback_data="confirmbuy_ETH"),
        types.InlineKeyboardButton("🔴 Продати BTC", callback_data="confirmsell_BTC"),
    )

    bot.send_message(message.chat.id, report_text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call: types.CallbackQuery) -> None:
    data = call.data
    if data.startswith("confirmbuy_") or data.startswith("confirmsell_"):
        action, symbol = data.split("_", 1)
        verb = "купівлю" if action == "confirmbuy" else "продаж"
        bot.answer_callback_query(call.id, text="Підтверджено")
        bot.send_message(call.message.chat.id, f"✅ Ви підтвердили {verb} {symbol}")
    else:
        bot.answer_callback_query(call.id, text="Невідома дія")


if __name__ == "__main__":
    bot.infinity_polling()
