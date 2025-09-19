"""HTTP client wrapper used for all Binance SAPI/Spot calls."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests

from config_dev3 import (
    BINANCE_API_KEY,
    BINANCE_SECRET_KEY,
    BURST,
    EXCHANGEINFO_TTL_SEC,
    JITTER_MS,
    QPS,
)
from .utils import now_ms


LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.binance.com"
RECV_WINDOW = 5000
MAX_ATTEMPTS = 5

_SESSION = requests.Session()

_bucket_lock = threading.Lock()
_tokens = float(BURST)
_last_refill = time.monotonic()

_cache_lock = threading.Lock()
_exchange_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


def _jitter_range() -> Tuple[float, float]:
    if isinstance(JITTER_MS, (tuple, list)) and len(JITTER_MS) == 2:
        low, high = float(JITTER_MS[0]), float(JITTER_MS[1])
        if high < low:
            low, high = high, low
        return max(low, 0.0), max(high, 0.0)
    return 0.0, 0.0


def _micro_jitter() -> None:
    low, high = _jitter_range()
    if high <= 0:
        return
    delay = random.uniform(low, high) / 1000.0
    if delay > 0:
        time.sleep(delay)


def _acquire_token() -> None:
    global _tokens, _last_refill
    if float(QPS) <= 0:
        return

    while True:
        with _bucket_lock:
            now = time.monotonic()
            elapsed = now - _last_refill
            if elapsed > 0:
                _tokens = min(float(BURST), _tokens + elapsed * float(QPS))
                _last_refill = now
            if _tokens >= 1:
                _tokens -= 1
                return
            wait = (1 - _tokens) / float(QPS)
        time.sleep(max(wait, 0.01))


def _sign(params: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(params)
    payload["recvWindow"] = RECV_WINDOW
    payload["timestamp"] = now_ms()
    ordered = [(key, payload[key]) for key in sorted(payload)]
    query = urlencode(ordered, doseq=True)
    payload["signature"] = hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return payload


def _headers() -> Dict[str, str]:
    return {
        "X-MBX-APIKEY": BINANCE_API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _cache_key(path: str, params: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    if path != "/sapi/v1/convert/exchangeInfo":
        return None
    from_asset = params.get("fromAsset")
    to_asset = params.get("toAsset")
    if not from_asset or not to_asset:
        return None
    return (str(from_asset).upper(), str(to_asset).upper())


def _build_cached_response(path: str, payload: Dict[str, Any]) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    response.url = f"{BASE_URL}{path}"
    response.encoding = "utf-8"
    return response


def _get_cached(path: str, params: Dict[str, Any]) -> Optional[requests.Response]:
    key = _cache_key(path, params)
    if key is None:
        return None
    with _cache_lock:
        cached = _exchange_cache.get(key)
        if cached is None:
            return None
        expires_at, payload = cached
        if expires_at <= time.time():
            _exchange_cache.pop(key, None)
            return None
    LOGGER.debug("exchangeInfo cache hit for %s/%s", *key)
    return _build_cached_response(path, payload)


def _store_cache(path: str, params: Dict[str, Any], payload: Dict[str, Any]) -> None:
    key = _cache_key(path, params)
    if key is None:
        return
    ttl = max(int(EXCHANGEINFO_TTL_SEC), 0)
    expires_at = time.time() + ttl if ttl else time.time()
    with _cache_lock:
        _exchange_cache[key] = (expires_at, payload)


def _backoff_delay(attempt: int) -> float:
    base = min(2 ** (attempt - 1), 16)
    jitter_low, jitter_high = _jitter_range()
    if jitter_high <= 0:
        return float(base)
    jitter = random.uniform(jitter_low, jitter_high) / 1000.0
    return float(base) + jitter


def _should_jitter(path: str) -> bool:
    return path.startswith("/sapi/v1/convert/") and "exchangeInfo" not in path


def _request(method: str, path: str, params: Optional[Dict[str, Any]]) -> requests.Response:
    params = params or {}

    cached = _get_cached(path, params)
    if cached is not None:
        return cached

    url = f"{BASE_URL}{path}"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        LOGGER.debug("HTTP %s %s attempt=%s", method, path, attempt)
        signed = _sign(params)
        if _should_jitter(path):
            _micro_jitter()
        _acquire_token()
        try:
            if method == "GET":
                response = _SESSION.get(url, params=signed, headers=_headers(), timeout=10)
            else:
                response = _SESSION.post(url, data=signed, headers=_headers(), timeout=10)
        except requests.RequestException as exc:
            LOGGER.warning("Request error %s %s attempt=%s: %s", method, path, attempt, exc)
            if attempt >= MAX_ATTEMPTS:
                raise
            time.sleep(_backoff_delay(attempt))
            continue

        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code == 200:
            if isinstance(payload, dict) and str(payload.get("code")) not in {"0", "None", "null", "NoneType", None}:
                code = payload.get("code")
                try:
                    code_int = int(code)
                except (TypeError, ValueError):
                    code_int = code
                if code_int == -1021:
                    LOGGER.warning("Timestamp drift detected; retrying immediately")
                    continue
                if code_int in {-1003, 429}:
                    delay = _backoff_delay(attempt)
                    LOGGER.warning(
                        "API rate error %s on %s %s attempt=%s; sleeping %.2fs",
                        code,
                        method,
                        path,
                        attempt,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                LOGGER.error("API error %s on %s %s: %s", code, method, path, payload)
                raise requests.HTTPError(str(payload))

            if isinstance(payload, dict):
                _store_cache(path, params, payload)
            LOGGER.info("HTTP %s %s succeeded", method, path)
            return response

        error_code = None
        if isinstance(payload, dict):
            try:
                error_code = int(payload.get("code"))
            except (TypeError, ValueError):
                error_code = payload.get("code")

        if error_code == -1021:
            LOGGER.warning("Timestamp error on %s %s; retrying", method, path)
            continue

        if response.status_code == 429 or error_code in {-1003, 429}:
            delay = _backoff_delay(attempt)
            LOGGER.warning(
                "Rate limit hit on %s %s attempt=%s; sleeping %.2fs",
                method,
                path,
                attempt,
                delay,
            )
            time.sleep(delay)
            continue

        if attempt >= MAX_ATTEMPTS:
            LOGGER.error(
                "Request failed after %s attempts: %s %s status=%s payload=%s",
                attempt,
                method,
                path,
                response.status_code,
                payload,
            )
            response.raise_for_status()
            return response

        delay = _backoff_delay(attempt)
        LOGGER.warning(
            "Retrying %s %s status=%s in %.2fs", method, path, response.status_code, delay
        )
        time.sleep(delay)

    raise RuntimeError(f"Failed to call {method} {path} after {MAX_ATTEMPTS} attempts")


def get(path: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """Perform a signed GET request to the Binance API."""

    return _request("GET", path, params)


def post(path: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """Perform a signed POST request to the Binance API."""

    return _request("POST", path, params)
