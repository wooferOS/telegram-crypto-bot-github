from datetime import datetime
from binance_api import get_historical_prices


def get_asian_range(symbol: str, limit=96) -> tuple[float, float]:
    """Asian range: 00:00–08:00 UTC → 8 годин, 5-хвилинні свічки = 96 штук"""
    prices = get_historical_prices(symbol, interval="5m", limit=limit)
    highs = [candle["high"] for candle in prices]
    lows = [candle["low"] for candle in prices]
    return max(highs), min(lows)


def is_breakout(symbol: str, price: float) -> bool:
    high, low = get_asian_range(symbol)
    return price > high or price < low
