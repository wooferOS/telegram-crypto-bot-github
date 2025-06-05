from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException
import os

load_dotenv(dotenv_path=os.path.expanduser("~/.env"))

api_key = os.getenv("BINANCE_API_KEY", "")
api_secret = os.getenv("BINANCE_SECRET_KEY", "")

if not api_key or not api_secret:
    print("BINANCE credentials not provided")
    exit()

client = Client(api_key=api_key, api_secret=api_secret)

try:
    info = client.get_account()
    print("✅ Binance access works")
    print(info)
except BinanceAPIException as e:
    print(f"❌ Binance API error: {e}")
