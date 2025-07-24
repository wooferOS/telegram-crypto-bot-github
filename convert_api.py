import hmac
import hashlib
import logging
import time
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Any, Set, Optional

import requests

from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY
from utils_dev3 import get_current_timestamp
from quote_counter import increment_quote_usage
import convert_logger
from binance_api import get_spot_price, get_precision, get_lot_step

BASE_URL = "https://api.binance.com"

_session = requests.Session()
logger = logging.getLogger(__name__)
logged_quote_errors: Set[tuple[str, str]] = set()

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




def get_available_to_tokens(from_token: str) -> List[str]:
    url = f"{BASE_URL}/sapi/v1/convert/exchangeInfo"
    params = _sign({"fromAsset": from_token})
    resp = _session.get(url, params=params, headers=_headers(), timeout=10)
    data = resp.json()
    # Ensure compatibility with both list and dict responses
    if isinstance(data, list):
        data = {"toAssetList": data}
    return [item.get("toAsset") for item in data.get("toAssetList", [])]


def get_quote(
    from_token: str, to_token: str, amount: float, max_retries: int = 3
) -> Optional[Dict[str, Any]]:
    """Return quote data or None if invalid. Retries on missing price."""
    increment_quote_usage()
    url = f"{BASE_URL}/sapi/v1/convert/getQuote"

    try:
        precision = get_precision(from_token)
    except Exception:
        precision = 0
    if precision <= 0:
        step = get_lot_step(from_token).get("stepSize", "1")
        try:
            precision = max(-Decimal(step).as_tuple().exponent, 0)
        except Exception:
            precision = 0

    quant = Decimal("1") / (Decimal(10) ** precision)
    rounded_amount = float(Decimal(str(amount)).quantize(quant, rounding=ROUND_DOWN))
    amount = rounded_amount

    params = _sign({"fromAsset": from_token, "toAsset": to_token, "fromAmount": amount})

    quote: Optional[Dict[str, Any]] = None
    for i in range(max_retries):
        logger.info(
            f"🔁 Спроба {i+1}/{max_retries} отримати quote {from_token} → {to_token} з amount={amount:.10f}"
        )
        try:
            resp = _session.post(url, data=params, headers=_headers(), timeout=10)
            data = resp.json()
        except Exception as exc:  # pragma: no cover - network
            logger.warning("[dev3] get_quote error %s → %s: %s", from_token, to_token, exc)
            data = None

        if isinstance(data, dict) and "ratio" in data:
            quote = data
            if quote.get("price") is not None:
                break
        else:
            if isinstance(data, dict) and data.get("code") == 345239:
                logger.warning("[dev3] 🟥 Binance limit reached 345239 for %s → %s", from_token, to_token)
                quote = {"code": 345239}
                break
            logger.warning(
                "[dev3] invalid quote for %s → %s: %s", from_token, to_token, data
            )
            quote = data if isinstance(data, dict) else None

        time.sleep(0.2)

    if not quote or quote.get("price") is None:
        if (from_token, to_token) not in logged_quote_errors:
            logger.warning(
                f"❌ Усі спроби отримати quote для {from_token} → {to_token} не дали результату (price=None)"
            )
            logged_quote_errors.add((from_token, to_token))
    if quote is not None:
        quote["created_at"] = time.time()  # зберігаємо час створення котирування
    return quote


def get_quote_with_retry(from_token: str, to_token: str, base_amount: float) -> Optional[Dict[str, Any]]:
    """Retry get_quote with increasing amounts until price is available."""
    for multiplier in [1, 2, 5, 10, 20, 50, 100, 200]:
        amount = base_amount * multiplier
        logger.info(
            f"[dev3] Retrying quote {from_token} → {to_token} з amount={amount}"
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
            if quote.get("price"):
                return quote
    logger.info(
        f"[dev3] ⛔️ Всі спроби get_quote завершились без price для {from_token} → {to_token}"
    )
    if quote and quote.get("price") is None:
        convert_logger.log_quote_skipped(from_token, to_token, reason="amount_too_low")
    return None


def accept_quote(quote: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Accept a quote if it is still valid."""
    created_at = quote.get("created_at")
    if created_at and (time.time() - created_at > 9.5):  # TTL Binance ~10s
        convert_logger.log_quote_skipped(
            quote["fromAsset"],
            quote["toAsset"],
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
        if isinstance(data, dict) and not data.get("success", True):
            msg = data.get("msg", "")
            code = data.get("code")
            if code in (-23000, 345103) or "quoteId expired" in msg:
                convert_logger.log_quote_skipped(
                    quote["fromAsset"],
                    quote["toAsset"],
                    reason=msg or str(code),
                )
            else:
                convert_logger.log_conversion_error(
                    quote["fromAsset"], quote["toAsset"], msg or str(code)
                )
            return None
        return data
    except Exception as e:
        error_msg = str(e)
        convert_logger.log_conversion_error(
            quote.get("fromAsset"), quote.get("toAsset"), error_msg
        )
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
