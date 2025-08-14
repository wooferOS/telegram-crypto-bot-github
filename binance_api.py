import json
import random
import time
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests
from binance.client import Client
from config_dev3 import BINANCE_API_KEY, BINANCE_API_SECRET

from convert_logger import logger

BASE_URL = "https://api.binance.com"

_session = requests.Session()

# caches
_price_cache: Dict[str, tuple[float, float]] = {}
_exchange_cache: dict | None = None
_exchange_cache_time: float = 0.0
_EXCHANGE_CACHE_PATH = Path(tempfile.gettempdir()) / "binance_exchange_info.json"


# Return authenticated Binance client
def get_binance_client():
    return Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)


def get_token_balance(asset: str, wallet: str = "SPOT") -> float:
    """Уніфікований доступ до балансу. FUNDING не використовуємо — повертаємо SPOT."""
    # ``wallet`` зберігається для сумісності, але завжди використовуємо SPOT.
    if not asset:
        return 0.0
    asset = asset.upper()
    try:
        client = get_binance_client()
        bal = client.get_asset_balance(asset=asset)
        if bal:
            return float(bal.get("free") or 0.0)
    except Exception as exc:  # pragma: no cover - network
        logger.warning(
            f"[dev3] get_token_balance fallback SPOT: asset={asset} err={exc}"
        )
    return 0.0

try:
    from config_dev3 import VALID_PAIRS
except Exception:  # pragma: no cover - optional config
    VALID_PAIRS: set[str] | None = None



def _load_exchange_info() -> dict:
    """Return exchangeInfo JSON with 5 minute disk cache."""
    global _exchange_cache, _exchange_cache_time
    now = time.time()

    if _exchange_cache and now - _exchange_cache_time < 300:
        return _exchange_cache

    if _EXCHANGE_CACHE_PATH.exists():
        try:
            mtime = _EXCHANGE_CACHE_PATH.stat().st_mtime
            if now - mtime < 300:
                with open(_EXCHANGE_CACHE_PATH, "r", encoding="utf-8") as f:
                    _exchange_cache = json.load(f)
                    _exchange_cache_time = mtime
                    return _exchange_cache
        except Exception:
            pass

    try:
        resp = requests.get(f"{BASE_URL}/api/v3/exchangeInfo", timeout=5)
        if resp.status_code == 200:
            _exchange_cache = resp.json()
            _exchange_cache_time = now
            try:
                with open(_EXCHANGE_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(_exchange_cache, f)
            except Exception:
                pass
            return _exchange_cache
        logger.warning(
            f"[dev3] ⚠️ exchangeInfo HTTP {resp.status_code}: {resp.text}"
        )
    except Exception as exc:  # pragma: no cover - network
        logger.warning(f"[dev3] ⚠️ exchangeInfo error: {exc}")

    return _exchange_cache or {}


def get_valid_symbols() -> set[str]:
    """Return cached set of valid trading pairs from Binance."""
    data = _load_exchange_info()
    return {
        s.get("symbol")
        for s in data.get("symbols", [])
        if s.get("status") == "TRADING"
    }


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


def get_spot_price(symbol_or_base: str) -> Optional[float]:
    """Return current spot price for ``symbol_or_base`` using public API."""
    if not symbol_or_base:
        return None

    token = symbol_or_base.upper()
    symbol = token if token.endswith("USDT") else f"{token}USDT"

    now = time.time()
    cached = _price_cache.get(symbol)
    if cached and now - cached[1] < 60:
        return cached[0]

    if not is_symbol_supported(symbol):
        logger.debug(f"[dev3] is_symbol_supported False for {symbol}")
        return None

    url = f"{BASE_URL}/api/v3/ticker/price"
    for attempt in range(3):
        try:
            resp = _session.get(url, params={"symbol": symbol}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                price = float(data.get("price", 0.0))
                if price > 0:
                    _price_cache[symbol] = (price, now)
                    logger.debug(f"[dev3] get_spot_price {symbol} -> {price}")
                    return price
                logger.warning(
                    f"[dev3] ⚠️ get_spot_price non-positive price for {symbol}: {data}"
                )
                return None
            if resp.status_code in (429,) or resp.status_code >= 500:
                logger.warning(
                    f"[dev3] ⚠️ get_spot_price HTTP {resp.status_code} for {symbol}"
                )
                if attempt < 2:
                    time.sleep(0.2 + random.random() * 0.3)
                    continue
            else:
                logger.warning(
                    f"[dev3] ⚠️ get_spot_price HTTP {resp.status_code} for {symbol}: {resp.text}"
                )
            return None
        except Exception as exc:  # pragma: no cover - network
            logger.exception(f"[dev3] ❌ get_spot_price error for {symbol}: {exc}")
            return None
    return None


def is_symbol_supported(symbol: str) -> bool:
    """Return True if ``symbol`` is trading against USDT."""
    if not symbol:
        return False
    symbol = symbol.upper()

    data = _load_exchange_info()
    for s in data.get("symbols", []):
        if s.get("symbol") == symbol:
            if s.get("status") != "TRADING":
                logger.debug(
                    f"[dev3] is_symbol_supported {symbol} status {s.get('status')}"
                )
                return False
            if s.get("quoteAsset") != "USDT":
                logger.debug(
                    f"[dev3] is_symbol_supported {symbol} quote {s.get('quoteAsset')}"
                )
                return False
            return True
    logger.debug(f"[dev3] is_symbol_supported {symbol} not found")
    return False


# Backward compatibility
def get_symbol_price(symbol: str) -> Optional[float]:
    """Return current price for ``symbol`` using :func:`get_spot_price`."""
    if not symbol:
        return None
    return get_spot_price(symbol)


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
    return is_symbol_supported(symbol)


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
            raw_price = get_spot_price(symbol)
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
