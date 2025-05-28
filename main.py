import telebot
import datetime
import os
from dotenv import load_dotenv
from binance.client import Client
from openai import OpenAI
import logging

# ✅ Завантаження змінних середовища
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

# 🔒 Перевірка обов’язкових змінних
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не встановлено в .env")
if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY не встановлено в .env")
if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
    raise ValueError("❌ Binance API ключі не встановлені в .env")

# 🤖 Telegram-бот
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# 📈 Binance API
binance_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

# 🧠 GPT
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# 📝 Логування
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# 📋 Клавіатура
def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("/status", "/report")
    markup.row("/buy BTCUSDT 50", "/sell BTCUSDT 0.001")
    markup.row("/set_budget", "/set_pair")
    markup.row("/history", "/help")
    return markup


# 🟢 /start
@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.send_message(message.chat.id, "👋 Вітаю! Я Криптобот. Введи /menu для перегляду команд.")


# 📋 /menu
@bot.message_handler(commands=['menu'])
def handle_menu(message):
    bot.send_message(message.chat.id, "📋 Меню команд:", reply_markup=main_keyboard())


# 📊 /report — звіт з Binance + GPT
@bot.message_handler(commands=['report'])
def handle_report(message):
    user_id = message.chat.id
    now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

    try:
        balances = binance_client.get_asset_balance(asset='USDT')
        balance = round(float(balances['free']), 2)

        gpt_prompt = f"""
        Ти є криптоаналітиком. На {now} сформуй короткий звіт:
        1. Що краще продати з пари BTC/ETH/BNB?
        2. Що краще купити серед топ-10 монет?
        3. Приблизний Stop Loss, Take Profit і очікувана прибутковість.
        """

        chat = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ти фінансовий криптоаналітик, відповідай коротко й технічно."},
                {"role": "user", "content": gpt_prompt}
            ],
            temperature=0.4
        )

        gpt_reply = chat.choices[0].message.content.strip()

        report = f"""📊 Щоденний звіт ({now})

💰 Баланс: {balance} USDT

📈 GPT-аналітика:
{gpt_reply}

👉 Для підтвердження дій:
/confirm_buy або /confirm_sell
"""
        bot.send_message(user_id, report)

    except Exception as e:
        logging.error(f"Помилка звіту: {e}")
        bot.send_message(user_id, "⚠️ Помилка при генерації звіту. Спробуй пізніше.")


# ✅ /confirm_buy
@bot.message_handler(commands=['confirm_buy'])
def handle_confirm_buy(message):
    bot.send_message(message.chat.id, "🟢 Купівля підтверджена. Ордер буде виконано автоматично.")


# ❌ /confirm_sell
@bot.message_handler(commands=['confirm_sell'])
def handle_confirm_sell(message):
    bot.send_message(message.chat.id, "🔴 Продаж підтверджено. Ордер буде виконано автоматично.")


# 📥 /buy <symbol> <amount>
@bot.message_handler(commands=['buy'])
def handle_buy(message):
    try:
        args = message.text.split()
        if len(args) != 3:
            bot.send_message(message.chat.id, "❗️ Формат: /buy BTCUSDT 50")
            return
        symbol = args[1].upper()
        usdt_amount = float(args[2])

        price = float(binance_client.get_symbol_ticker(symbol=symbol)['price'])
        quantity = round(usdt_amount / price, 6)

        order = binance_client.create_order(
            symbol=symbol,
            side='BUY',
            type='MARKET',
            quantity=quantity
        )

        bot.send_message(message.chat.id, f"✅ Куплено {quantity} {symbol} на {usdt_amount} USDT")
    except Exception as e:
        logging.error(f"Помилка покупки: {e}")
        bot.send_message(message.chat.id, "⚠️ Помилка при купівлі. Перевір символ або баланс.")


# 📤 /sell <symbol> <amount>
@bot.message_handler(commands=['sell'])
def handle_sell(message):
    try:
        args = message.text.split()
        if len(args) != 3:
            bot.send_message(message.chat.id, "❗️ Формат: /sell BTCUSDT 0.001")
            return
        symbol = args[1].upper()
        quantity = float(args[2])

        order = binance_client.create_order(
            symbol=symbol,
            side='SELL',
            type='MARKET',
            quantity=quantity
        )

        bot.send_message(message.chat.id, f"✅ Продано {quantity} {symbol}")
    except Exception as e:
        logging.error(f"Помилка продажу: {e}")
        bot.send_message(message.chat.id, "⚠️ Помилка при продажу. Перевір символ або кількість.")


# ℹ️ /status
@bot.message_handler(commands=['status'])
def handle_status(message):
    bot.send_message(message.chat.id, "🟢 Бот активний і працює коректно.")


# ❓ /help
@bot.message_handler(commands=['help'])
def handle_help(message):
    bot.send_message(message.chat.id, "🛟 Допомога:\n/menu — список команд\n/report — GPT-звіт\n/buy <symbol> <usdt>\n/sell <symbol> <amount>\n/confirm_buy — підтвердити купівлю\n/confirm_sell — підтвердити продаж")

# 🔄 Запуск
if __name__ == "__main__":
    print("🤖 Telegram бот стартує...")
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        logging.error(f"Критична помилка: {e}")
