import hmac
import hashlib
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Set

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

try:  # pragma: no cover - optional config
    from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY
except Exception:  # pragma: no cover - used in tests
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "test")
    BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "test")

from utils_dev3 import get_current_timestamp
from quote_counter import increment_quote_usage

BASE_URL = os.getenv("BINANCE_API_BASE", "https://api.binance.com")

_session = requests.Session()
_retry = Retry(total=3, backoff_factor=0.0, status_forcelist=(429, 418))
_session.mount("https://", HTTPAdapter(max_retries=_retry))
logger = logging.getLogger(__name__)

_supported_pairs_cache: Optional[Set[str]] = None
_pairs_cache_time: float = 0
PAIRS_TTL = 1800  # seconds


def _sign(params: Dict[str, Any]) -> Dict[str, Any]:
    params["timestamp"] = get_current_timestamp()
    query = "&".join(f"{k}={v}" for k, v in params.items())
    signature = hmac.new(BINANCE_SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature
    return params


def _headers() -> Dict[str, str]:
    return {"X-MBX-APIKEY": BINANCE_API_KEY, "Content-Type": "application/x-www-form-urlencoded"}


def _request(method: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    attempt = 0
    while True:
        attempt += 1
        time.sleep(random.uniform(0.05, 0.15))
        signed = _sign(params.copy())
        try:
            if method == "GET":
                resp = _session.get(url, params=signed, headers=_headers(), timeout=10)
            else:
                resp = _session.post(url, data=signed, headers=_headers(), timeout=10)
        except requests.RequestException as exc:  # pragma: no cover - network errors
            if attempt >= 3:
                raise
            time.sleep(2 ** attempt)
            continue
        if resp.status_code in (429, 418):
            retry_after = float(resp.headers.get("Retry-After", 0))
            if retry_after:
                time.sleep(retry_after)
            else:
                time.sleep(2 ** attempt)
            if attempt >= 3:
                break
            continue
        data = resp.json()
        if isinstance(data, dict) and data.get("code") in (-1003, 345239):
            if attempt >= 3:
                break
            time.sleep(2 ** attempt)
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


def get_available_to_tokens(from_token: str) -> List[str]:
    params = {"fromAsset": from_token}
    data = _request("GET", "/sapi/v1/convert/exchangeInfo", params)
    if isinstance(data, list):
        data = {"toAssetList": data}
    return [item.get("toAsset") for item in data.get("toAssetList", [])]


def get_quote(from_token: str, to_token: str, amount: float) -> Dict[str, Any]:
    increment_quote_usage()
    params = {"fromAsset": from_token, "toAsset": to_token, "fromAmount": amount}
    return _request("POST", "/sapi/v1/convert/getQuote", params)


def accept_quote(quote_id: str) -> Dict[str, Any]:
    params = {"quoteId": quote_id}
    return _request("POST", "/sapi/v1/convert/acceptQuote", params)


def get_all_supported_convert_pairs() -> Set[str]:
    global _supported_pairs_cache, _pairs_cache_time
    now = time.time()
    if _supported_pairs_cache is None or now - _pairs_cache_time > PAIRS_TTL:
        data = _request("GET", "/sapi/v1/convert/exchangeInfo", {})
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
