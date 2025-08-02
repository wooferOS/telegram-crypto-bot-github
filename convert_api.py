import hmac
import hashlib
import logging
import time
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Any, Set, Optional
import re
import json
import os

import requests
from urllib.parse import urlencode

from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY
from utils_dev3 import get_current_timestamp, round_step_size, safe_float
from quote_counter import increment_quote_usage
import convert_logger
from convert_logger import log_error, log_conversion_success, log_conversion_error
from binance_api import get_spot_price, get_precision, get_lot_step

BASE_URL = "https://api.binance.com"

QUOTE_LIMITS_FILE = "quote_limits.json"

_quote_limits: Dict[str, Dict[str, float]] | None = None
_quote_limits_updated = False

_session = requests.Session()
logger = logging.getLogger(__name__)
logged_quote_errors: Set[tuple[str, str]] = set()

_supported_pairs_cache: Optional[Set[str]] = None


def log_msg(message: str, level: str = "info") -> None:
    """Simple logging helper respecting level argument."""
    if level == "error":
        logger.error(message)
    elif level == "warning":
        logger.warning(message)
    else:
        logger.info(message)

# Cache of discovered minimal amounts per pair
_min_amount_cache: Dict[tuple[str, str], float] = {}


def sanitize_token_pair(from_token: str, to_token: str) -> str:
    """Return standardized key for quote limits."""
    if not from_token or not to_token:
        logger.warning("[dev3] ❌ Невірний токен: token=None під час symbol.upper()")
        return ""
    return f"{from_token.upper()}→{to_token.upper()}"


def load_quote_limits() -> Dict[str, Dict[str, float]]:
    """Load cached quote limits from file once per cycle."""
    global _quote_limits
    if _quote_limits is None:
        if os.path.exists(QUOTE_LIMITS_FILE):
            try:
                with open(QUOTE_LIMITS_FILE, "r", encoding="utf-8") as f:
                    _quote_limits = json.load(f)
            except Exception:
                _quote_limits = {}
        else:
            _quote_limits = {}
    return _quote_limits


def save_quote_limits() -> None:
    """Persist quote limits if they were updated."""
    global _quote_limits_updated
    if _quote_limits is not None and _quote_limits_updated:
        with open(QUOTE_LIMITS_FILE, "w", encoding="utf-8") as f:
            json.dump(_quote_limits, f, indent=2)
        _quote_limits_updated = False


def is_within_quote_limits(symbol_from: str, symbol_to: str, amount_from: float, quote_limits: Dict[str, Dict[str, float]]) -> bool:
    key = f"{symbol_from}_{symbol_to}"
    limits = quote_limits.get(key)
    if not limits:
        return True  # Якщо немає кешу — пробуємо
    min_amount = float(limits.get("min_amount", 0))
    max_amount = float(limits.get("max_amount", float('inf')))
    return min_amount <= amount_from <= max_amount


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


def _parse_min_amount(msg: str) -> Optional[float]:
    """Extract minimal amount value from Binance error message."""
    numbers = re.findall(r"[0-9]*\.?[0-9]+", msg)
    if numbers:
        try:
            return float(numbers[0])
        except ValueError:
            return None
    return None


def _validate_min_amount(from_token: str, to_token: str, amount: float) -> Optional[float]:
    """Call Binance Convert getQuote with validateOnly to detect minimal amount."""
    url = f"{BASE_URL}/sapi/v1/convert/getQuote"
    params = _sign(
        {
            "fromAsset": from_token,
            "toAsset": to_token,
            "fromAmount": amount,
            "validateOnly": True,
        }
    )
    try:
        resp = _session.post(url, data=params, headers=_headers(), timeout=10)
        data = resp.json()
    except Exception as exc:  # pragma: no cover - network
        logger.warning(
            "[dev3] validateOnly error %s → %s: %s", from_token, to_token, exc
        )
        return None

    if isinstance(data, dict):
        if data.get("code") == 345233:
            msg = data.get("msg", "")
            min_val = _parse_min_amount(msg)
            if min_val is not None:
                _min_amount_cache[(from_token, to_token)] = min_val
                return min_val
        if data.get("ratio") is not None:
            _min_amount_cache[(from_token, to_token)] = amount
            return amount
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


def get_quote(from_asset: str, to_asset: str, amount: float) -> Optional[Dict[str, Any]]:
    """Fetch quote from Binance Convert API and return parsed data."""
    endpoint = "/sapi/v1/convert/getQuote"
    timestamp = int(time.time() * 1000)
    params = {
        "fromAsset": from_asset,
        "toAsset": to_asset,
        "fromAmount": amount,
        "recvWindow": 5000,
        "timestamp": timestamp,
    }
    query_string = urlencode(params)
    signature = hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    full_url = f"{BASE_URL}{endpoint}?{query_string}&signature={signature}"
    try:
        response = requests.post(full_url, headers=headers)
        data = response.json()

        if "ratio" in data and "toAmount" in data:
            return {
                "ratio": float(data["ratio"]),
                "inverseRatio": float(data.get("inverseRatio", 0)),
                "fromAmount": float(data["fromAmount"]),
                "toAmount": float(data["toAmount"]),
                "validUntil": data.get("validTimestamp"),
            }
        else:
            convert_logger.warning(
                f"❌ No valid quote returned for {from_asset} → {to_asset}: {data}"
            )
            return None
    except Exception as e:  # pragma: no cover - network
        convert_logger.error(
            f"❌ Exception in get_quote() for {from_asset} → {to_asset}: {str(e)}"
        )
        return None


def get_quote_with_retry(
    from_token: str,
    to_token: str,
    base_amount: float,
    quote_limits: Dict[str, Dict[str, float]] | None = None,
) -> Optional[Dict[str, Any]]:
    """Retry get_quote with increasing amounts until price is available."""
    min_required = get_min_convert_amount(from_token, to_token)
    amount_from = base_amount
    if amount_from < min_required:
        logger.warning(
            f"[dev3] ⚠️ {from_token} → {to_token} має надто малу кількість ({amount_from:.2f} < {min_required:.2f}) — підставляємо мінімальну для спроби quote"
        )
        amount_from = min_required

    for multiplier in [1, 2, 5, 10, 20, 50, 100, 200]:
        amount = amount_from * multiplier
        logger.info(
            f"[dev3] Retrying quote {from_token} → {to_token} з amount={amount}"
        )
        logger.info(
            f"[dev3] 🟡 getQuote: {from_token} → {to_token}, amount = {amount}"
        )
        quote = get_quote(from_token, to_token, amount)
        if quote:
            if quote.get("msg") == "amount too low":
                logger.warning(
                    f"[dev3] ❌ Binance Convert API: amount too low for {from_token} → {to_token}"
                )
            if quote.get("code") == 345239:
                return None
            created_at = quote.get("created_at")
            if created_at and time.time() - created_at > 9.5:
                continue
            if quote.get("ratio"):
                return quote
    logger.info(
        f"[dev3] ⛔️ Всі спроби get_quote завершились без price для {from_token} → {to_token}"
    )
    if quote and quote.get("ratio") is None:
        convert_logger.log_quote_skipped(from_token, to_token, reason="amount_too_low")
    return None


def accept_quote(
    quote: Dict[str, Any], from_token: str, to_token: str
) -> Optional[Dict[str, Any]]:
    """Accept a quote if it is still valid."""
    if not from_token or not to_token:
        convert_logger.logger.warning(
            "[dev3] ❌ Один із токенів None у accept_quote: from_token=%s, to_token=%s",
            from_token,
            to_token,
        )
        convert_logger.log_quote_skipped(
            from_token or "None",
            to_token or "None",
            reason="⛔️ Пропущено: invalid_tokens",
        )
        return None
    created_at = quote.get("created_at")
    if created_at and (time.time() - created_at > 9.5):  # TTL Binance ~10s
        convert_logger.log_quote_skipped(
            from_token,
            to_token,
            reason="⛔️ Пропущено: quoteId протерміновано",
        )
        return None

    quote_id = quote.get("quoteId")
    if not quote_id:
        return None

    url = f"{BASE_URL}/sapi/v1/convert/acceptQuote"
    params = _sign({"quoteId": quote_id})
    try:
        resp = _session.post(url, data=params, headers=_headers(), timeout=10)
        data = resp.json()
        logger.info("[dev3] Binance response (accept_quote): %s", data)
    except Exception as e:
        error_msg = str(e)
        log_conversion_error(from_token, to_token, error_msg)
        return None

    if data and data.get("success") is True:
        profit = safe_float(data.get("toAmount", 0)) - safe_float(
            data.get("fromAmount", 0)
        )
        log_conversion_success(from_token, to_token, profit)
        logger.info(f"[dev3] 🔄 accept_quote виконано: {quote_id}")
        return data

    log_conversion_error(from_token, to_token, data)
    return None


def get_min_convert_amount(from_token: str, to_token: str) -> float:
    """Return minimal allowed amount for conversion via Binance Convert API."""
    key = (from_token, to_token)
    cached = _min_amount_cache.get(key)
    if cached is not None:
        return cached

    min_val = _validate_min_amount(from_token, to_token, 0.00000001)
    return float(min_val) if min_val is not None else 0.0


def get_max_convert_amount(from_token: str, to_token: str) -> float:
    """Return maximal allowed amount for conversion based on cached limits."""
    limits = load_quote_limits()
    key_underscore = f"{from_token}_{to_token}"
    key_arrow = sanitize_token_pair(from_token, to_token)
    info = limits.get(key_underscore) or limits.get(key_arrow)
    if info:
        return float(info.get("max_amount") or info.get("max") or float("inf"))
    return float("inf")


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


def get_supported_pairs():
    url = "https://api.binance.com/sapi/v1/convert/exchangeInfo"
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()  # це вже список
    except Exception as e:
        log_error(f"❌ Error fetching supported pairs: {str(e)}")
        return []


def get_quote_for_pair(from_asset: str, to_asset: str, amount: float) -> Optional[dict]:
    """Отримати котирування (quote) для пари через Binance Convert."""
    url = "https://api.binance.com/sapi/v1/convert/getQuote"
    headers = {
        "X-MBX-APIKEY": BINANCE_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "fromAsset": from_asset,
        "toAsset": to_asset,
        "fromAmount": str(amount),
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log_error(
            f"❌ Error getting quote for {from_asset} → {to_asset} with amount {amount}: {str(e)}"
        )
        return None


def get_valid_quote(from_token: str, to_token: str, from_amount: float) -> Optional[Dict[str, Any]]:
    """Attempt to fetch quote for the entire amount without splitting."""
    try:
        quote = get_quote(from_token, to_token, from_amount)
        if quote is None or quote.get("ratio") is None:
            return None
        return quote
    except Exception as e:  # pragma: no cover - network/logging only
        log_msg(
            f"❌ Error getting quote for {from_token} → {to_token} with amount {from_amount}: {e}",
            level="error",
        )
        return None
