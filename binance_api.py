import requests
from convert_logger import logger

BASE_URL = "https://api.binance.com"

_VALID_SYMBOLS: set[str] | None = None


def get_valid_symbols() -> set[str]:
    """Return cached set of valid trading pairs from Binance."""
    global _VALID_SYMBOLS
    if _VALID_SYMBOLS is None:
        try:
            url = f"{BASE_URL}/api/v3/exchangeInfo"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            _VALID_SYMBOLS = {
                s["symbol"]
                for s in data.get("symbols", [])
                if s.get("status") == "TRADING"
            }
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.warning(f"[dev3] ❌ get_valid_symbols failed: {exc}")
            _VALID_SYMBOLS = set()
    return _VALID_SYMBOLS


def get_historical_prices(symbol: str, interval: str = "5m", limit: int = 100):
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        test_symbol = symbol + "USDT"
    else:
        test_symbol = symbol

    if test_symbol not in get_valid_symbols():
        logger.warning(f"[dev3] ❌ Symbol {test_symbol} не знайдено на Binance")
        return []

    url = f"{BASE_URL}/api/v3/klines"
    params = {"symbol": test_symbol, "interval": interval, "limit": limit}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if isinstance(data, dict) and data.get("code") == -1121:
            logger.warning(
                f"[dev3] ❌ get_historical_prices failed for {test_symbol}: {data.get('msg')}"
            )
            return []

        if not isinstance(data, list) or not all(
            isinstance(item, list) and len(item) >= 6 for item in data
        ):
            raise ValueError(f"Invalid response from Binance for {test_symbol}: {data}")

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
        logger.warning(f"[dev3] ❌ get_historical_prices failed for {test_symbol}: {exc}")
        return []


def get_last_prices(symbol: str, limit: int = 100):
    candles = get_historical_prices(symbol, limit=limit)
    return [c["close"] for c in candles]
