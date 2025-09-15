
from __future__ import annotations


# === unified secret loader (config_dev3.py only) BEGIN ===
def get_binance_api_keys():
    """
    Джерело ключів тільки одне: config_dev3.py
    Секретний файл не змінюємо і не логуємо значення ключів.
    """
    try:
        import config_dev3 as _cfg
    except Exception as e:
        raise RuntimeError("Не знайдено модуль config_dev3.py у PYTHONPATH") from e

    key = getattr(_cfg, "BINANCE_API_KEY", None)
    sec = getattr(_cfg, "BINANCE_API_SECRET", None)
    if not key or not sec:
        raise RuntimeError("В config_dev3.py відсутні BINANCE_API_KEY/BINANCE_API_SECRET")

    return key, sec

# Для сумісності зі старим кодом, який читає os.environ:
# підставляємо туди значення з config_dev3.py (джерело все одно одне).
try:
    _k, _s = get_binance_api_keys()
    os.environ["BINANCE_API_KEY"] = _k
    os.environ["BINANCE_API_SECRET"] = _s
except Exception:
    pass
# === unified secret loader (config_dev3.py only) END ===

import os
"""Low level helpers for Binance Spot/SAPI Convert endpoints.

This module focuses on correctly signing and sending requests to Binance.
It implements a minimal retry policy with exponential backoff. Only
``application/x-www-form-urlencoded`` payloads are used for POST requests in
order to comply with Binance requirements.

The functions exposed here are intentionally lightweight so they can be
mocked easily in tests.  They **must not** log or expose API secrets.
"""

import hashlib
import hmac
import logging
import random
import time
from typing import Any, Dict, List, Optional, Set
from quote_counter import try_consume_getquote, init_run_budget

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from config_dev3 import (
    DEV3_RECV_WINDOW_MS,
    DEV3_RECV_WINDOW_MAX_MS,
    API_BASE,
)

from utils_dev3 import get_current_timestamp
from quote_counter import increment_quote_usage, record_weight


BINANCE_API_KEY, BINANCE_API_SECRET = get_binance_api_keys()


# Convert endpoints always live under the main API domain; use configured base
BASE_URL = API_BASE
DEFAULT_RECV_WINDOW = DEV3_RECV_WINDOW_MS

# requests session with a tiny retry just for connection errors.  Rate limit
# handling is done manually below.
_session = requests.Session()
_retry = Retry(total=3, backoff_factor=0, status_forcelist=(418, 429))
_session.mount("https://", HTTPAdapter(max_retries=_retry))
logger = logging.getLogger(__name__)

# cache for supported Convert pairs
_supported_pairs_cache: Optional[Set[str]] = None
_pairs_cache_time: float = 0
PAIRS_TTL = 1800  # seconds

# cache for exchangeInfo responses
_exchange_info_cache: Optional[Dict[str, Any]] = None
_exchange_info_time: float = 0

# offset between local time and Binance server time
_time_offset_ms = 0
# whether we already synchronised time with Binance
_time_synced = False

# quoteIds already processed via acceptQuote
_accepted_quotes: Set[str] = set()


class ClockSkewError(Exception):
    """Raised when Binance reports timestamp drift (-1021)."""


def _current_timestamp() -> int:
    """Return current timestamp in milliseconds including server offset."""
    return get_current_timestamp() + _time_offset_ms


def _sync_time() -> None:
    """Synchronise local clock with Binance server time."""
    global _time_offset_ms, _time_synced
    try:
        resp = _session.get(f"{BASE_URL}/api/v3/time", timeout=10)
        server_time = int(resp.json().get("serverTime", 0))
        _time_offset_ms = server_time - get_current_timestamp()
    except Exception:  # pragma: no cover - network
        _time_offset_ms = 0
    _time_synced = True


def _build_signed_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return parameters with timestamp, recvWindow clamp and signature."""

    params = params.copy()
    recv = int(params.get("recvWindow", DEV3_RECV_WINDOW_MS))
    recv = max(1, min(recv, DEV3_RECV_WINDOW_MAX_MS))
    params["recvWindow"] = recv
    params["timestamp"] = _current_timestamp()
    query = "&".join(f"{k}={v}" for k, v in params.items())
    signature = hmac.new(
        BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    params["signature"] = signature
    return params


def _headers() -> Dict[str, str]:
    return {
        "X-MBX-APIKEY": BINANCE_API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _backoff(attempt: int) -> float:
    """Exponential backoff with jitter."""
    base = 0.5 * (2 ** (attempt - 1))
    return min(base, 30.0) + random.uniform(0, 0.25)


def _request(method: str, path: str, params: Dict[str, Any], *, signed: bool = True) -> Dict[str, Any]:
    """Send a request to Binance with optional signing and retry."""

    url = f"{BASE_URL}{path}"
    tried_time_sync = False
    if signed and not _time_synced:
        _sync_time()
    for attempt in range(1, 6):
        payload = _build_signed_params(params) if signed else params
        headers = _headers() if signed else None
        try:
            if method == "GET":
                resp = _session.get(url, params=payload, headers=headers, timeout=10)
            else:
                resp = _session.post(url, data=payload, headers=headers, timeout=10)
        except requests.RequestException:  # pragma: no cover - network
            if attempt >= 5:
                raise
            time.sleep(_backoff(attempt))
            continue

        if resp.status_code >= 500 or resp.status_code in (418, 429):
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else _backoff(attempt)
            time.sleep(delay)
            continue

        data = resp.json()

        if isinstance(data, dict):
            code = data.get("code")
            if code is not None:
                logger.warning("Binance error %s: %s", code, data.get("msg"))
            if code == -1021:
                time.sleep(_backoff(attempt))
                if not tried_time_sync:
                    tried_time_sync = True
                    _sync_time()
                continue
            if code == -1022:
                raise ValueError("Signature for this request is not valid")
            if code in (-1102, -1103):
                raise ValueError("Missing or invalid parameter")
            if code in (-2014, -2015):
                raise PermissionError("Invalid API-key or permissions")
            if code == 345239:
                raise RuntimeError("Convert quota exceeded")
            if code == -1003:
                time.sleep(_backoff(attempt))
                continue

        return data

    raise RuntimeError("Request failed after retries")


def get_balances() -> Dict[str, float]:
    """Return current wallet balances using ``POST /sapi/v3/asset/getUserAsset``.

    Docs: https://developers.binance.com/docs/wallet/asset/user-assets
    """
    record_weight("getUserAsset")
    params = {"needBtcValuation": "false", "recvWindow": DEFAULT_RECV_WINDOW}  # timestamp+signature added in _request
    data = _request(
        "POST",
        "/sapi/v3/asset/getUserAsset",
        params,
    )
    balances: Dict[str, float] = {}
    if isinstance(data, list):
        for bal in data:
            total = float(bal.get("free", 0)) + float(bal.get("locked", 0))
            if total > 0:
                balances[bal.get("asset", "")] = total
    return balances


def exchange_info(**params: Any) -> Dict[str, Any]:
    """Return Convert exchange information (public, cached)."""

    global _exchange_info_cache, _exchange_info_time
    if not params:
        now = time.time()
        if _exchange_info_cache and now - _exchange_info_time < PAIRS_TTL:
            return _exchange_info_cache

    record_weight("exchangeInfo")
    data = _request("GET", "/sapi/v1/convert/exchangeInfo", params, signed=False)

    if not params:
        _exchange_info_cache = data
        _exchange_info_time = time.time()
    return data


def asset_info(asset: str) -> Dict[str, Any]:
    """Return precision and limits for a single asset via Convert ``assetInfo``."""

    record_weight("assetInfo")
    data = _request(
        "GET", "/sapi/v1/convert/assetInfo", {"asset": asset}, signed=False
    )
    if isinstance(data, dict):
        return data
    for item in data or []:
        if item.get("asset") == asset:
            return item
    return {}


def get_available_to_tokens(from_token: str) -> List[str]:
    data = exchange_info(fromAsset=from_token)
    if isinstance(data, list):
        data = {"toAssetList": data}
    return [item.get("toAsset") for item in data.get("toAssetList", [])]


def get_quote_with_id(
    from_asset: str,
    to_asset: str,
    from_amount: Optional[float] = None,
    to_amount: Optional[float] = None,
    walletType: Optional[str] = None,
    validTime: str = "10s",
    recvWindow: int = DEFAULT_RECV_WINDOW,
) -> Dict[str, Any]:
    """Request a quote with optional ``validTime``.

    Exactly one of ``from_amount`` or ``to_amount`` must be set.
    ``validTime`` accepts ``10s``, ``30s`` or ``1m``.
    """

    if (from_amount is None) == (to_amount is None):
        raise ValueError("Provide exactly one of from_amount or to_amount")

    increment_quote_usage()
    params = {
        "fromAsset": from_asset,
        "toAsset": to_asset,
        "validTime": validTime,
    }
    if from_amount is not None:
        params["fromAmount"] = from_amount
    if to_amount is not None:
        params["toAmount"] = to_amount
    if walletType:
        params["walletType"] = walletType
    params["recvWindow"] = recvWindow  # timestamp + signature added in _request
    return _request("POST", "/sapi/v1/convert/getQuote", params)


def get_quote(
    from_token: str,
    to_token: str,
    amount: float,
    *,
    validTime: str = "10s",
) -> Dict[str, Any]:
    """Backward compatible helper for :func:`get_quote_with_id`."""
    return get_quote_with_id(
        from_token, to_token, from_amount=amount, validTime=validTime
    )


def accept_quote(quote_id: str) -> Dict[str, Any]:
    if quote_id in _accepted_quotes:
        logger.info("[dev3] Duplicate acceptQuote ignored for %s", quote_id)
        return {"duplicate": True, "quoteId": quote_id}
    _accepted_quotes.add(quote_id)
    record_weight("acceptQuote")
    params = {"quoteId": quote_id, "recvWindow": DEFAULT_RECV_WINDOW}  # timestamp+signature added in _request
    return _request("POST", "/sapi/v1/convert/acceptQuote", params)


def get_order_status(orderId: Optional[str] = None, quoteId: Optional[str] = None) -> Dict[str, Any]:
    """Return order status by ``orderId`` or ``quoteId`` (exactly one)."""

    if (orderId is None) == (quoteId is None):
        raise ValueError("Provide exactly one of orderId or quoteId")

    record_weight("orderStatus")
    params = {"orderId": orderId} if orderId is not None else {"quoteId": quoteId}
    params["recvWindow"] = DEFAULT_RECV_WINDOW
    return _request("GET", "/sapi/v1/convert/orderStatus", params)


def get_quote_status(order_id: str) -> Dict[str, Any]:
    return get_order_status(orderId=order_id)


def trade_flow(
    startTime: int,
    endTime: int,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrapper for ``GET /sapi/v1/convert/tradeFlow`` endpoint.

    ``startTime`` and ``endTime`` are mandatory according to Binance docs. A
    ``ValueError`` is raised if either is omitted.
    """

    if startTime is None or endTime is None:
        raise ValueError("startTime and endTime are required")

    MAX_SPAN = 30 * 24 * 60 * 60 * 1000
    if endTime - startTime > MAX_SPAN:
        raise ValueError("convert/tradeFlow range must be ≤ 30 days")

    params: Dict[str, Any] = {
        "startTime": startTime,
        "endTime": endTime,
    }
    if limit is not None:
        params["limit"] = limit
    if cursor is not None:
        params["cursor"] = cursor
    record_weight("tradeFlow")
    data = _request("GET", "/sapi/v1/convert/tradeFlow", params)
    return {"list": data.get("list", []), "cursor": data.get("cursor")}


def get_all_supported_convert_pairs() -> Set[str]:
    global _supported_pairs_cache, _pairs_cache_time
    now = time.time()
    if _supported_pairs_cache is None or now - _pairs_cache_time > PAIRS_TTL:
        data = exchange_info()
        pairs: Set[str] = set()
        if isinstance(data, dict):
            for item in data.get("fromAssetList", []):
                from_asset = item.get("fromAsset")
                for to in item.get("toAssetList", []):
                    to_asset = to.get("toAsset")
                    if from_asset and to_asset:
                        pairs.add(f"{from_asset}{to_asset}")
        _supported_pairs_cache = pairs
        _pairs_cache_time = now
    return _supported_pairs_cache


def is_valid_convert_pair(from_token: str, to_token: str) -> bool:
    symbol = f"{from_token}{to_token}"
    return symbol in get_all_supported_convert_pairs()
# === Convert: exchange info helpers ===
def get_convert_pairs():
    """
    Обгортає /sapi/v1/convert/exchangeInfo.
    Повертає те, що віддає Binance (dict або list) як є.
    """
    return _request("GET", "/sapi/v1/convert/exchangeInfo", {})

def get_convert_pair_info(from_asset: str, to_asset: str):
    """
    Витягнути інформацію по конкретній парі (from_asset -> to_asset)
    із exchangeInfo. Повертає dict або None.
    """
    data = get_convert_pairs()
    items = data if isinstance(data, list) else (data.get("data") or data.get("symbols") or data)
    if not isinstance(items, (list, tuple)):
        return None
    from_a, to_a = (str(from_asset or '').upper(), str(to_asset or '').upper())
    for it in items:
        fa = str(it.get("fromAsset", it.get("baseAsset", ""))).upper()
        ta = str(it.get("toAsset", it.get("quoteAsset", ""))).upper()
        if fa == from_a and ta == to_a:
            return it
    return None


# --- quota backoff (injected by ops) ---
try:
    import os, json, time
    from datetime import datetime, timezone, timedelta

    REGION = os.environ.get("REGION","GLOBAL").lower()
    _QUOTA_FLAG = f"/run/convert.quota.block.{REGION}"

    def _quota_blocked():
        try:
            with open(_QUOTA_FLAG) as f:
                data = json.load(f)
            return time.time() < float(data.get("until", 0))
        except Exception:
            return False

    def _set_quota_block(seconds, code, msg):
        try:
            os.makedirs("/run", exist_ok=True)
            with open(_QUOTA_FLAG, "w") as f:
                json.dump({"until": time.time()+float(seconds), "code": int(code), "msg": str(msg)}, f)
        except Exception:
            pass

    # Зберігаємо оригінальну реалізацію і підміняємо зверху
    __request_impl = _request

    def _request(method, path, params, *, signed: bool = True):

        # Fast-fail: skip hitting Convert when quota is cached
        try:
            if _quota_blocked() and str(path).startswith('/sapi/v1/convert/'):
                raise RuntimeError('Convert quota cached locally')
        except Exception:
            pass
        # Не ліземо в Convert, якщо квота вже закешована
        if path.startswith("/sapi/v1/convert/") and _quota_blocked():
            raise RuntimeError("Convert quota exceeded (cached)")
        try:
            return __request_impl(method, path, params, signed=signed)
        except Exception as e:
            emsg = str(e)
            if path.startswith("/sapi/v1/convert/"):
                code = 0
                if "345239" in emsg or "daily quotation limit" in emsg or "Convert quota exceeded" in emsg:
                    code = 345239
                elif "345103" in emsg or "hourly quotation limit" in emsg:
                    code = 345103

                if code == 345239:
                    # До наступної доби UTC + 5 хв
                    now = datetime.now(timezone.utc)
                    tomorrow = (now + timedelta(days=1)).date()
                    until = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=5)
                    _set_quota_block(until.timestamp() - now.timestamp(), code, "daily quota")
                elif code == 345103:
                    _set_quota_block(60*60, code, "hourly quota")
            raise
# --- end quota backoff ---
except Exception:
    pass


# --- quota backoff v2 (global-aware) ---
try:
    import os, json, time
    REGION = os.environ.get("REGION","GLOBAL").lower()
    _VARIANTS = [REGION] if REGION not in ("", "global") else ["america","asia","global"]

    def _quota_blocked():
        now = time.time()
        for r in _VARIANTS:
            path = f"/run/convert.quota.block.{r}"
            try:
                with open(path) as f:
                    data = json.load(f)
                if now < float(data.get("until", 0)):
                    return True
            except Exception:
                pass
        return False

    def _set_quota_block_multi(seconds, code, msg):
        try:
            os.makedirs("/run", exist_ok=True)
            payload = {"until": time.time()+float(seconds), "code": int(code), "msg": str(msg)}
            for r in _VARIANTS:
                path = f"/run/convert.quota.block.{r}"
                try:
                    with open(path, "w") as f:
                        json.dump(payload, f)
                except Exception:
                    pass
        except Exception:
            pass

    # Перекриваємо попередній варіант, якщо був
    try:
        _set_quota_block = _set_quota_block_multi
    except Exception:
        pass
except Exception:
    pass
# --- end quota backoff v2 ---
