import os
import matplotlib.pyplot as plt
import pandas as pd
from telegram import Bot
from dotenv import load_dotenv

# Завантаження змінних середовища (якщо потрібно)
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
bot = Bot(token=TELEGRAM_TOKEN)

# Демонстраційні дані — можна замінити на Binance API
dates = pd.date_range(end=pd.Timestamp.today(), periods=7)
coins = ['BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'SOL', 'DOT', 'DOGE', 'AVAX', 'MATIC']
price_data = {coin: [100 + i * 5 + (j * 3) for j in range(7)] for i, coin in enumerate(coins)}

# Побудова графіку
df = pd.DataFrame(price_data, index=dates)
plt.figure(figsize=(12, 6))
for coin in coins:
    plt.plot(df.index, df[coin], label=coin)
plt.title("📊 Топ-10 монет — Динаміка цін")
plt.xlabel("Дата")
plt.ylabel("Ціна (умовна)")
plt.legend()
plt.grid(True)
plt.tight_layout()

# Збереження в PNG
plot_path = "top10_prices_analysis.png"
plt.savefig(plot_path)
plt.close()

# Відправка графіку в Telegram
with open(plot_path, 'rb') as photo:
    bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=photo,
        caption="🧾 Щоденний графік: топ-10 монет 📈"
    )
