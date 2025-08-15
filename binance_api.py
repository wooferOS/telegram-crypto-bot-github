import json
import random
import time
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import math
import pathlib
import logging

import requests
from binance.client import Client
from config_dev3 import BINANCE_API_KEY, BINANCE_API_SECRET
from json_sanitize import safe_load_json

logger = logging.getLogger(__name__)

BASE_URL = "https://api.binance.com"

_session = requests.Session()

# caches
_price_cache: Dict[str, tuple[float, float]] = {}
_exchange_cache: dict | None = None
_exchange_cache_time: float = 0.0
_EXCHANGE_CACHE_PATH = Path(tempfile.gettempdir()) / "binance_exchange_info.json"


def _log_convert_error(resp: requests.Response) -> None:
    try:
        j = resp.json()
    except Exception:
        j = {"raw": resp.text}
    logger.error(
        "Convert API error: status=%s code=%s msg=%s body=%s",
        resp.status_code,
        j.get("code"),
        j.get("msg"),
        j,
    )


# --- конверт-мапа символів ---
_CONVERT_MAP: Dict[str, str] = {}


def _load_convert_map() -> Dict[str, str]:
    """Load convert asset mapping from convert_assets_config.json."""
    global _CONVERT_MAP
    if _CONVERT_MAP:
        return _CONVERT_MAP
    cfg = pathlib.Path("convert_assets_config.json")
    if cfg.exists():
        try:
            data = safe_load_json(cfg)
            mp: Dict[str, str] = {}
            if isinstance(data, dict):
                if isinstance(data.get("map"), dict):
                    mp = {str(k).upper(): str(v).upper() for k, v in data["map"].items()}
                elif isinstance(data.get("aliases"), dict):
                    mp = {
                        str(k).upper(): str(v).upper()
                        for k, v in data.get("aliases", {}).items()
                    }
                elif isinstance(data.get("aliases"), list):
                    for row in data.get("aliases", []):
                        s = str(row.get("spot", "")).upper()
                        c = str(row.get("convert", "")).upper()
                        if s and c:
                            mp[s] = c
            _CONVERT_MAP = mp
        except Exception as e:  # pragma: no cover - invalid json
            logger.warning("convert map load failed: %s", e)
    return _CONVERT_MAP


def to_convert_symbol(asset: str) -> str:
    if not asset:
        return asset
    m = _load_convert_map()
    a = str(asset).upper()
    return m.get(a, a)


# Return authenticated Binance client
def get_binance_client():
    return Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)


def get_token_balance(asset: str, wallet: str = "SPOT", client: Client | None = None) -> float:
    """Return token balance from SPOT or FUNDING wallet."""
    try:
        client = client or get_binance_client()
        a = str(asset).upper()
        if wallet.upper() == "FUNDING":
            rows = client.sapi_get_asset_getfundingasset(asset=a)
            if isinstance(rows, list):
                for r in rows:
                    if str(r.get("asset", "")).upper() == a:
                        return float(r.get("free", 0.0) or 0.0)
            return 0.0
        bal = client.get_asset_balance(asset=a) or {}
        return float(bal.get("free", 0.0) or 0.0)
    except Exception as e:  # pragma: no cover - network
        logger.warning("get_token_balance error asset=%s wallet=%s: %s", asset, wallet, e)
        return 0.0


def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _spot_price(symbol: str) -> Optional[float]:
    """Return spot price for pair like BTCUSDT."""
    try:
        t = get_binance_client().get_symbol_ticker(symbol=symbol)
        return _safe_float(t.get("price"))
    except Exception:
        return None


def get_quote(
    from_asset: str,
    to_asset: str,
    amount_from: Optional[float] = None,
    amount_quote: Optional[float] = None,
    wallet: str = "SPOT",
) -> Optional[Dict[str, Any]]:
    """Unified getQuote for Binance Convert with manual signing and walletType fallback."""
    import hmac
    import hashlib
    import urllib.parse

    fa = to_convert_symbol(from_asset)
    ta = to_convert_symbol(to_asset)

    amount = 0.0
    if amount_from and amount_from > 0:
        amount = float(amount_from)
    elif amount_quote and amount_quote > 0:
        spot_sym = f"{fa}{ta}"
        px = _spot_price(spot_sym)
        if px and px > 0:
            amount = float(amount_quote) / px
        else:
            amount = float(amount_quote) * 0.000001

    if amount <= 0:
        amount = 11.0
        logger.info("ℹ️ amount скориговано до %s для getQuote (dev3 paper)", amount)

    def _request(w: str) -> requests.Response:
        params = {
            "fromAsset": fa,
            "toAsset": ta,
            "fromAmount": amount,
            "walletType": w,
            "recvWindow": 50000,
            "timestamp": int(time.time() * 1000),
        }
        qs = urllib.parse.urlencode(params, doseq=True)
        sig = hmac.new(BINANCE_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
        headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
        return requests.post(
            f"{BASE_URL}/sapi/v1/convert/getQuote",
            headers=headers,
            data=qs + "&signature=" + sig,
            timeout=15,
        )

    resp = _request(wallet)
    if resp.status_code != 200:
        try:
            j = resp.json()
        except Exception:
            j = {}
        _log_convert_error(resp)
        if j.get("code") == -9000:
            alt = "FUNDING" if wallet == "SPOT" else "SPOT"
            logger.info("↩️ retry getQuote with walletType=%s for %s→%s", alt, fa, ta)
            resp = _request(alt)
            if resp.status_code != 200:
                _log_convert_error(resp)
                return None
        else:
            return None

    data = resp.json()
    qid = data.get("quoteId")
    if not qid:
        logger.warning("Convert getQuote: 200 but no quoteId. body=%s", data)
        return None
    return {
        "quoteId": qid,
        "fromAsset": fa,
        "toAsset": ta,
        "toAmount": _safe_float(data.get("toAmount")),
        "ratio": _safe_float(data.get("ratio")),
        "raw": data,
    }

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
                try:
                    _exchange_cache = safe_load_json(_EXCHANGE_CACHE_PATH)
                    _exchange_cache_time = mtime
                    return _exchange_cache
                except Exception:
                    pass
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
