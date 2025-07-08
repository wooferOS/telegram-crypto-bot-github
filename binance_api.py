import requests
from convert_logger import logger

BASE_URL = "https://api.binance.com"


def get_historical_prices(symbol: str, interval: str = "5m", limit: int = 100):
    url = f"{BASE_URL}/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if not isinstance(data, list) or not all(
            isinstance(item, list) and len(item) >= 6 for item in data
        ):
            raise ValueError(f"Invalid response from Binance for {symbol}: {data}")

        candles = []
        for item in data:
            candles.append(
                {
                    "timestamp": int(item[0]),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                }
            )
        return candles
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.warning(f"[dev3] \u274c get_historical_prices failed for {symbol}: {exc}")
        return []


def get_last_prices(symbol: str, limit: int = 100):
    candles = get_historical_prices(symbol, limit=limit)
    return [c["close"] for c in candles]
