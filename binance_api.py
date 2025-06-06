import os
from dotenv import load_dotenv
from binance.client import Client

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")

_client = Client(api_key=API_KEY, api_secret=API_SECRET)

def get_client() -> Client:
    """Return initialized Binance client."""
    return _client


def get_balance() -> list:
    """Return raw balance list from Binance."""
    return _client.get_account().get("balances", [])


def create_market_order(symbol: str, side: str, quantity: float):
    """Create a market order on Binance."""
    return _client.create_order(symbol=symbol, side=side, type="MARKET", quantity=quantity)
