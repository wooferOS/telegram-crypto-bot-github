from binance_api import get_candlestick_klines
from ml_model import train_and_save_model

klines = get_candlestick_klines("BTC", interval="1d", limit=180)
train_and_save_model(klines)
print("✅ Модель навчена і збережена.")
