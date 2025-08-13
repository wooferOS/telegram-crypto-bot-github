import time
from decimal import Decimal
from typing import Optional, List, Dict, Any

import requests
from binance.client import Client
from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY

from convert_logger import logger

BASE_URL = "https://api.binance.com"

_session = requests.Session()

# Return authenticated Binance client
def get_binance_client():
    return Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

# Cache for spot prices: {token: (price, timestamp)}
_price_cache: Dict[str, tuple[float, float]] = {}

_VALID_SYMBOLS: set[str] | None = None
try:
    from config_dev3 import VALID_PAIRS
except Exception:  # pragma: no cover - optional config
    VALID_PAIRS: set[str] | None = None


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
    if not symbol:
        logger.warning("[dev3] ❌ Невірний токен: token=None під час symbol.upper()")
        return []
    symbol = symbol.upper()

    if not symbol.endswith("USDT"):
        logger.warning(f"[dev3] ❌ Symbol {symbol} не є парою з USDT")
        return []

    valid_pairs = VALID_PAIRS or get_valid_symbols()
    if symbol not in valid_pairs:
        logger.warning(f"[dev3] ❌ Symbol {symbol} не знайдено на Binance")
        return []

    url = f"{BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if isinstance(data, dict) and data.get("code") == -1121:
            logger.warning(
                f"[dev3] ❌ get_historical_prices failed for {symbol}: {data.get('msg')}"
            )
            return []

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
        logger.warning(f"[dev3] ❌ get_historical_prices failed for {symbol}: {exc}")
        return []


def get_last_prices(symbol: str, limit: int = 100):
    candles = get_historical_prices(symbol, limit=limit)
    return [c["close"] for c in candles]


def get_spot_price(token: str) -> Optional[float]:
    """Return current spot price of ``token`` in USDT with 60s cache."""
    if not token:
        logger.warning("[dev3] ❌ Невірний токен: token=None під час symbol.upper()")
        return None
    token = token.upper()
    now = time.time()
    cached = _price_cache.get(token)
    if cached and now - cached[1] < 60:
        return cached[0]

    symbol = f"{token}USDT"
    # самопари (USDTUSDT) не мають сенсу
    if len(symbol) > 4 and symbol[: len(symbol) // 2] == symbol[len(symbol) // 2 :]:
        logger.warning("[dev3] ⚠️ get_spot_price skip self-symbol %s", symbol)
        return None
    if not is_symbol_supported(symbol):
        logger.warning("[dev3] ⚠️ get_spot_price unsupported symbol %s", symbol)
        return None

    url = f"{BASE_URL}/api/v3/ticker/price"
    try:
        resp = _session.get(url, params={"symbol": symbol}, timeout=10)
        data = resp.json()
        price = data.get("price")
        if price is None:
            logger.warning(
                "[dev3] ⚠️ get_spot_price empty price for %s: %s", symbol, data
            )
            return None
        price_val = float(price)
        _price_cache[token] = (price_val, now)
        return price_val
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.warning("[dev3] ⚠️ get_spot_price error for %s: %s", symbol, exc)
        return None


def is_symbol_supported(symbol: str) -> bool:
    """Check if a trading pair exists on Binance spot market."""
    try:
        valid_pairs = VALID_PAIRS or get_valid_symbols()
        return symbol in valid_pairs
    except Exception:
        return False


# Backward compatibility
def get_symbol_price(symbol: str) -> Optional[float]:
    """Return current price for ``symbol`` with unified USDT suffix."""
    # 🔧 Уніфікація: прибираємо зайве "USDT" у кінці, якщо є
    if not symbol:
        logger.warning("[dev3] ❌ Невірний токен: token=None під час symbol.upper()")
        return None
    symbol = symbol.upper()
    if symbol.endswith("USDT") and not symbol.endswith("USDTUSDT"):
        symbol = symbol[:-4]
    symbol = f"{symbol}USDT"

    url = f"{BASE_URL}/api/v3/ticker/price"
    try:
        resp = _session.get(url, params={"symbol": symbol}, timeout=10)
        data = resp.json()
        return float(data["price"])
    except Exception as e:  # pragma: no cover - network/parse issues
        logger.warning(f"[dev3] ⚠️ Failed to get spot price for {symbol}: {e}")
        return None


def get_klines(symbol: str, interval: str = "5m", limit: int = 100) -> List[Dict[str, float]]:
    """Return historical klines data."""
    return get_historical_prices(symbol, interval=interval, limit=limit)


def get_24h_ticker_data(symbol: str) -> Dict[str, Any]:
    """Return 24h ticker data for the symbol."""
    url = f"{BASE_URL}/api/v3/ticker/24hr"
    try:
        if not symbol:
            logger.warning("[dev3] ❌ Невірний токен: token=None під час symbol.upper()")
            return {}
        resp = requests.get(url, params={"symbol": symbol.upper()}, timeout=10)
        return resp.json()
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.warning("[dev3] ⚠️ get_24h_ticker_data error for %s: %s", symbol, exc)
        return {}


def check_symbol_exists(from_token: str, to_token: str) -> bool:
    """Return True if ``to_token`` has a USDT pair on Binance."""
    if not to_token:
        logger.warning("[dev3] ❌ Невірний токен: token=None під час symbol.upper()")
        return False
    symbol = f"{to_token}USDT".upper()
    valid_pairs = VALID_PAIRS or get_valid_symbols()
    return symbol in valid_pairs


def get_ratio(base: str, quote: str) -> float:
    """Return ``quote/base`` price ratio using spot prices."""

    if not base or not quote:
        logger.warning(
            "[dev3] ❌ Невірний токен: token=None під час symbol.upper()"
        )
        return 0.0

    base = base.upper()
    quote = quote.upper()

    if base == quote:
        return 1.0

    if base == "USDT":
        price = get_spot_price(quote)
        return price or 0.0

    if quote == "USDT":
        price = get_spot_price(base)
        return (1.0 / price) if price else 0.0

    base_price = get_spot_price(base)
    quote_price = get_spot_price(quote)
    if not base_price or not quote_price:
        logger.warning(
            "[dev3] ❌ get_ratio failed: price lookup for %s or %s", base, quote
        )
        return 0.0
    return quote_price / base_price


def get_binance_balances() -> dict:
    """Return balance info for all tokens with USDT valuation."""
    client = get_binance_client()
    account_info = client.get_account()
    balances = account_info["balances"]

    result = {}
    total_usdt = 0.0

    for entry in balances:
        asset = entry["asset"]
        free = float(entry["free"])

        if free == 0 or asset in ["USDT", "BUSD"]:
            continue

        symbol = asset + "USDT"

        price = None
        usdt_value = 0.0
        try:
            raw_price = get_symbol_price(symbol)
            if raw_price is not None:
                price = float(raw_price)
                usdt_value = free * price
        except Exception as e:  # pragma: no cover - network/parse issues
            logger.warning(f"⚠️ Failed to fetch price for {symbol}: {e}")

        result[asset] = {
            "free": free,
            "price": price,
            "notional": usdt_value if price is not None else None,
            "usdt_value": usdt_value,
        }

        if usdt_value > 0.0:
            total_usdt += usdt_value

    result["total"] = round(total_usdt, 4)
    return result


_lot_step_cache: dict[str, dict] = {}


def get_lot_step(asset: str) -> dict:
    """Return LOT_SIZE filter for ``asset`` pair with USDT."""
    if not asset:
        logger.warning("[dev3] ❌ Невірний токен: token=None під час symbol.upper()")
        return {"stepSize": "1"}
    asset = asset.upper()
    if asset in _lot_step_cache:
        return _lot_step_cache[asset]
    url = f"{BASE_URL}/api/v3/exchangeInfo"
    try:
        resp = requests.get(url, params={"symbol": f"{asset}USDT"}, timeout=10)
        data = resp.json()
        for item in data.get("symbols", []):
            if item.get("symbol") == f"{asset}USDT":
                for f in item.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        _lot_step_cache[asset] = f
                        return f
    except Exception as exc:  # pragma: no cover - network
        logger.warning("[dev3] get_lot_step error for %s: %s", asset, exc)
    _lot_step_cache[asset] = {"stepSize": "1"}
    return _lot_step_cache[asset]


def get_precision(asset: str) -> int:
    """Return precision for an asset based on LOT_SIZE step."""
    step = get_lot_step(asset).get("stepSize", "1")
    try:
        precision = max(-Decimal(step).as_tuple().exponent, 0)
    except Exception:
        precision = 0
    return precision
