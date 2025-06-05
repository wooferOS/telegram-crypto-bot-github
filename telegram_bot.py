import os
from telebot import TeleBot, types
from dotenv import load_dotenv

from daily_analysis import generate_zarobyty_report

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable")

bot = TeleBot(TELEGRAM_BOT_TOKEN)


@bot.message_handler(commands=["zarobyty"])
def handle_zarobyty(message: types.Message) -> None:
    """Send profit report with inline buy/sell buttons."""
    report = generate_zarobyty_report()

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Купити ETH", callback_data="buy_eth"),
        types.InlineKeyboardButton("Продати BTC", callback_data="sell_btc"),
    )
    bot.send_message(message.chat.id, report, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data in ("buy_eth", "sell_btc"))
def handle_callbacks(call: types.CallbackQuery) -> None:
    if call.data == "buy_eth":
        text = "🟢 Купівля ETH підтверджена!"
    else:
        text = "🔴 Продаж BTC підтверджена!"
    bot.answer_callback_query(call.id, text)
    bot.send_message(call.message.chat.id, text)


if __name__ == "__main__":
    bot.infinity_polling()
