import hmac
import hashlib
import logging
from typing import Dict, List, Any, Set, Optional

import requests

from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY
from utils_dev3 import get_current_timestamp
from quote_counter import increment_quote_usage

BASE_URL = "https://api.binance.com"

_session = requests.Session()
logger = logging.getLogger(__name__)

_supported_pairs_cache: Optional[Set[str]] = None


def _sign(params: Dict[str, Any]) -> Dict[str, Any]:
    params["timestamp"] = get_current_timestamp()
    query = "&".join(f"{k}={v}" for k, v in params.items())
    signature = hmac.new(BINANCE_SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature
    return params


def _headers() -> Dict[str, str]:
    return {"X-MBX-APIKEY": BINANCE_API_KEY}


def get_balances() -> Dict[str, float]:
    url = f"{BASE_URL}/api/v3/account"
    params = _sign({})
    resp = _session.get(url, params=params, headers=_headers(), timeout=10)
    data = resp.json()
    balances: Dict[str, float] = {}
    for bal in data.get("balances", []):
        total = float(bal.get("free", 0)) + float(bal.get("locked", 0))
        if total > 0:
            balances[bal["asset"]] = total
    return balances


def get_symbol_price(token: str) -> Optional[float]:
    """Get current market price of a token (e.g., PEPE → PEPEUSDT)."""
    if token is None:
        logger.warning("symbol is None for quote: %s", token)
        return None
    symbol = f"{token.upper()}USDT"
    url = f"{BASE_URL}/api/v3/ticker/price"
    try:
        resp = _session.get(url, params={"symbol": symbol}, timeout=10)
        data = resp.json()
        return float(data["price"])
    except Exception as exc:
        logger.warning("[dev3] ⚠️ get_symbol_price error for %s: %s", symbol, exc)
        return None


def get_available_to_tokens(from_token: str) -> List[str]:
    url = f"{BASE_URL}/sapi/v1/convert/exchangeInfo"
    params = _sign({"fromAsset": from_token})
    resp = _session.get(url, params=params, headers=_headers(), timeout=10)
    data = resp.json()
    # Ensure compatibility with both list and dict responses
    if isinstance(data, list):
        data = {"toAssetList": data}
    return [item.get("toAsset") for item in data.get("toAssetList", [])]


def get_quote(from_token: str, to_token: str, amount: float) -> Optional[Dict[str, Any]]:
    """Return quote data or None if invalid."""
    increment_quote_usage()
    url = f"{BASE_URL}/sapi/v1/convert/getQuote"
    params = _sign({"fromAsset": from_token, "toAsset": to_token, "fromAmount": amount})
    try:
        resp = _session.post(url, data=params, headers=_headers(), timeout=10)
        data = resp.json()
    except Exception as exc:  # pragma: no cover - network
        logger.warning("[dev3] get_quote error %s → %s: %s", from_token, to_token, exc)
        return None

    if not isinstance(data, dict) or "ratio" not in data:
        logger.warning("[dev3] invalid quote for %s → %s: %s", from_token, to_token, data)
        return None
    return data


def get_quote_with_retry(from_token: str, to_token: str, base_amount: float) -> Optional[Dict[str, Any]]:
    """Retry get_quote with increasing amounts until price is available."""
    for multiplier in [1, 2, 5, 10]:
        amount = base_amount * multiplier
        logger.info(
            f"[dev3] 🔁 Retrying quote {from_token} → {to_token} з amount={amount}"
        )
        quote = get_quote(from_token, to_token, amount)
        if quote and quote.get("price"):
            return quote
    logger.info(
        f"[dev3] ⛔️ Всі спроби get_quote завершились без price для {from_token} → {to_token}"
    )
    return None


def accept_quote(quote_id: str) -> Optional[Dict[str, Any]]:
    url = f"{BASE_URL}/sapi/v1/convert/acceptQuote"
    params = _sign({"quoteId": quote_id})
    try:
        resp = _session.post(url, data=params, headers=_headers(), timeout=10)
        data = resp.json()
        logger.info("[dev3] Binance response (accept_quote): %s", data)
        return data
    except Exception as exc:
        logger.warning("[dev3] ❌ accept_quote exception %s: %s", quote_id, exc)
        return None


def get_all_supported_convert_pairs() -> Set[str]:
    """Return set of all supported convert pairs."""
    global _supported_pairs_cache
    if _supported_pairs_cache is None:
        url = f"{BASE_URL}/sapi/v1/convert/exchangeInfo"
        params = _sign({})
        try:
            resp = _session.get(url, params=params, headers=_headers(), timeout=10)
            data = resp.json()
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.warning("Failed to fetch convert pairs: %s", exc)
            data = {}

        pairs: Set[str] = set()
        if isinstance(data, dict):
            for item in data.get("fromAssetList", []):
                from_asset = item.get("fromAsset")
                for to in item.get("toAssetList", []):
                    to_asset = to.get("toAsset")
                    if from_asset and to_asset:
                        pairs.add(f"{from_asset}{to_asset}")
        _supported_pairs_cache = pairs
    return _supported_pairs_cache


def is_valid_convert_pair(from_token: str, to_token: str) -> bool:
    """Check if pair exists on Binance Convert."""
    valid_pairs = get_all_supported_convert_pairs()
    symbol = f"{from_token}{to_token}"
    return symbol in valid_pairs


def is_convertible_pair(from_token: str, to_token: str) -> bool:
    """Check via Binance Convert API if a pair can be converted."""
    url = f"{BASE_URL}/sapi/v1/convert/exchangeInfo"
    params = {"fromAsset": from_token, "toAsset": to_token}
    try:
        response = _session.get(url, headers=_headers(), params=params, timeout=5)
        data = response.json()
        return (
            isinstance(data, dict)
            and data.get("fromAsset") == from_token
            and data.get("toAsset") == to_token
        )
    except Exception as e:  # pragma: no cover - network
        logger.warning(
            f"[dev3] ❗️ Помилка при перевірці пари {from_token} → {to_token}: {e}"
        )
        return False
