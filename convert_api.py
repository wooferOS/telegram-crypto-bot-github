"""Low level helpers for Binance Spot/SAPI Convert endpoints.

This module focuses on correctly signing and sending requests to Binance.
It implements a minimal retry policy with exponential backoff and handles
timestamp drift (-1021 error) by syncing time with ``/api/v3/time``.  Only
``application/x-www-form-urlencoded`` payloads are used for POST requests in
order to comply with Binance requirements.

The functions exposed here are intentionally lightweight so they can be
mocked easily in tests.  They **must not** log or expose API secrets.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Set

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

try:  # pragma: no cover - optional config present only in production
    from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY
except Exception:  # pragma: no cover - used in tests/CI
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "test")
    BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "test")

from utils_dev3 import get_current_timestamp
from quote_counter import increment_quote_usage


BASE_URL = os.getenv("BINANCE_API_BASE", "https://api.binance.com")

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

# time offset between local machine and Binance server in milliseconds.  This
# value is adjusted whenever Binance returns error ``-1021``.
_time_offset_ms = 0


def _sync_time() -> None:
    """Synchronise local time with Binance server."""
    global _time_offset_ms
    try:
        resp = _session.get(f"{BASE_URL}/api/v3/time", timeout=10)
        server_time = resp.json().get("serverTime")
        if server_time:
            _time_offset_ms = int(server_time) - int(time.time() * 1000)
    except Exception:  # pragma: no cover - network issues
        pass


def _current_timestamp() -> int:
    """Return current timestamp adjusted by server offset."""
    return get_current_timestamp() + _time_offset_ms


def _sign(params: Dict[str, Any]) -> Dict[str, Any]:
    """Sign parameters using HMAC-SHA256.

    ``timestamp`` and default ``recvWindow`` are appended *after* existing
    parameters so that the order of keys matches the actual payload sent to
    Binance.
    """

    params = params.copy()
    params.setdefault("recvWindow", 20000)
    params["timestamp"] = _current_timestamp()
    query = "&".join(f"{k}={v}" for k, v in params.items())
    signature = hmac.new(
        BINANCE_SECRET_KEY.encode(), query.encode(), hashlib.sha256
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


def _request(method: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Send a signed request to Binance with retry and error handling."""

    url = f"{BASE_URL}{path}"
    for attempt in range(1, 6):
        signed = _sign(params)
        try:
            if method == "GET":
                resp = _session.get(url, params=signed, headers=_headers(), timeout=10)
            else:
                resp = _session.post(url, data=signed, headers=_headers(), timeout=10)
        except requests.RequestException as exc:  # pragma: no cover - network
            if attempt >= 5:
                raise
            time.sleep(_backoff(attempt))
            continue

        if resp.status_code in (418, 429):
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else _backoff(attempt)
            time.sleep(delay)
            continue

        data = resp.json()

        # timestamp drift
        if isinstance(data, dict) and data.get("code") == -1021:
            _sync_time()
            continue

        # hard rate limit / error codes
        if isinstance(data, dict) and data.get("code") in (-1003, 345239):
            time.sleep(_backoff(attempt))
            continue

        return data

    raise RuntimeError("Request failed after retries")


def get_balances() -> Dict[str, float]:
    data = _request("GET", "/api/v3/account", {})
    balances: Dict[str, float] = {}
    for bal in data.get("balances", []):
        total = float(bal.get("free", 0)) + float(bal.get("locked", 0))
        if total > 0:
            balances[bal["asset"]] = total
    return balances


def exchange_info(**params: Any) -> Dict[str, Any]:
    """Return Convert exchange information."""
    return _request("GET", "/sapi/v1/convert/exchangeInfo", params)


def get_available_to_tokens(from_token: str) -> List[str]:
    data = exchange_info(fromAsset=from_token)
    if isinstance(data, list):
        data = {"toAssetList": data}
    return [item.get("toAsset") for item in data.get("toAssetList", [])]


def get_quote_with_id(
    from_asset: str,
    to_asset: str,
    from_amount: float,
    walletType: Optional[str] = None,
) -> Dict[str, Any]:
    increment_quote_usage()
    params = {
        "fromAsset": from_asset,
        "toAsset": to_asset,
        "fromAmount": from_amount,
    }
    if walletType:
        params["walletType"] = walletType
    return _request("POST", "/sapi/v1/convert/getQuote", params)


def get_quote(from_token: str, to_token: str, amount: float) -> Dict[str, Any]:
    """Backward compatible wrapper."""
    return get_quote_with_id(from_token, to_token, amount)


def accept_quote(quote_id: str, walletType: Optional[str] = None) -> Dict[str, Any]:
    if os.getenv("PAPER", "1") == "1" or os.getenv("ENABLE_LIVE", "0") != "1":
        logger.info("[dev3] DRY-RUN: acceptQuote skipped for %s", quote_id)
        return {"dryRun": True}
    params = {"quoteId": quote_id}
    if walletType:
        params["walletType"] = walletType
    return _request("POST", "/sapi/v1/convert/acceptQuote", params)


def get_quote_status(order_id: str) -> Dict[str, Any]:
    return _request("GET", "/sapi/v1/convert/orderStatus", {"orderId": order_id})


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
