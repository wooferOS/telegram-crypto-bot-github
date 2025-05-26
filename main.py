import os
import logging
import telebot
import openai
import schedule
import time
import matplotlib.pyplot as plt
from datetime import datetime
from binance.client import Client
import requests

# --- Логування ---
logging.basicConfig(
    filename='daily_analysis.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Ініціалізація ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
openai.api_key = OPENAI_API_KEY
binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# --- Telegram команди ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    bot.send_message(message.chat.id, "👋 Привіт! Я CryptoBot. Напиши /menu для початку.")

@bot.message_handler(commands=['menu'])
def menu(message):
    menu_text = (
        "📋 Меню команд:\n"
        "/start — Почати роботу\n"
        "/status — Поточний баланс Binance\n"
        "/report — GPT-аналітика\n"
        "/buy — Купити BTCUSDT\n"
        "/sell — Продати BTCUSDT\n"
        "/help — Підказка"
    )
    bot.send_message(message.chat.id, menu_text)

@bot.message_handler(commands=['status'])
def status_handler(message):
    try:
        account = binance_client.get_account()
        assets = [f"{a['asset']}: {a['free']}" for a in account['balances'] if float(a['free']) > 0.0]
        text = "💼 Поточний баланс Binance:\n" + "\n".join(assets)
        bot.send_message(message.chat.id, text)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка: {e}")

@bot.message_handler(commands=['report'])
def report_handler(message):
    try:
        btc = binance_client.get_symbol_ticker(symbol="BTCUSDT")
        eth = binance_client.get_symbol_ticker(symbol="ETHUSDT")
        prompt = f"BTC: {btc['price']}, ETH: {eth['price']}. Що купити або продати?"

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        reply = response.choices[0].message.content.strip()
        bot.send_message(message.chat.id, f"🤖 GPT каже:\n{reply}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ GPT-звіт недоступний: {e}")

@bot.message_handler(commands=['buy'])
def buy_handler(message):
    try:
        order = binance_client.create_order(
            symbol='BTCUSDT',
            side='BUY',
            type='MARKET',
            quantity=0.0002
        )
        bot.send_message(message.chat.id, f"✅ Купівля виконана: {order['fills'][0]['qty']} BTC")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка купівлі: {e}")

@bot.message_handler(commands=['sell'])
def sell_handler(message):
    try:
        order = binance_client.create_order(
            symbol='BTCUSDT',
            side='SELL',
            type='MARKET',
            quantity=0.0002
        )
        bot.send_message(message.chat.id, f"✅ Продаж виконано: {order['fills'][0]['qty']} BTC")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка продажу: {e}")

@bot.message_handler(commands=['help'])
def help_handler(message):
    bot.send_message(message.chat.id, "🆘 Напиши /menu щоб побачити всі доступні команди")

@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.send_message(message.chat.id, "❔ Невідома команда. Напиши /menu")

# --- Графік та щоденний аналіз ---
def run_daily_analysis():
    try:
        prices = binance_client.get_all_tickers()
        top = sorted([(p['symbol'], float(p['price'])) for p in prices if 'USDT' in p['symbol']], key=lambda x: -x[1])[:10]

        # Побудова графіка
        symbols = [x[0] for x in top]
        values = [x[1] for x in top]
        plt.figure(figsize=(10,5))
        plt.bar(symbols, values, color='skyblue')
        plt.title("Топ 10 монет по ціні")
        plt.xticks(rotation=45)
        plt.tight_layout()
        filename = f"top10_{datetime.now().strftime('%Y%m%d')}.png"
        plt.savefig(filename)

        summary = "📈 Топ 10 монет Binance:\n" + "\n".join([f"{s}: {v:.2f}" for s,v in top])
        with open(filename, 'rb') as photo:
            bot.send_photo(ADMIN_CHAT_ID, photo=photo, caption=summary)

        logging.info("✅ Звіт відправлено")
    except Exception as e:
        logging.error(f"❌ Звіт не вдалось згенерувати: {e}")

# --- Автозапуск о 09:00 ---
schedule.every().day.at("09:00").do(run_daily_analysis)

# --- Запуск бота ---
if __name__ == '__main__':
    bot.send_message(ADMIN_CHAT_ID, f"🚀 Crypto Bot запущено: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    while True:
        schedule.run_pending()
        time.sleep(60)
        bot.polling(none_stop=True)
