"""Thin HTTP client for Binance Spot/SAPI endpoints."""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from typing import Any, Dict, Optional, Tuple

import requests
from requests import Response
from urllib.parse import urlencode

from config_dev3 import (
    BINANCE_API_KEY,
    BINANCE_SECRET_KEY,
    BURST,
    EXINFO_TTL_SEC,
    QPS,
)
from src.core.utils import now_ms

LOGGER = logging.getLogger(__name__)
BASE_URL = os.environ.get("BINANCE_API_BASE", "https://api.binance.com")
RECV_WINDOW_MS = 5000
MAX_BACKOFF_ATTEMPTS = 5

_session = requests.Session()

_tokens = float(BURST)
_last_refill = time.monotonic()
_bucket_lock = threading.Lock()

_exchange_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_time_offset_ms = 0
_time_lock = threading.Lock()


def _acquire_token() -> None:
    """Simple token bucket enforcement for QPS/BURST."""
    global _tokens, _last_refill
    with _bucket_lock:
        while True:
            now = time.monotonic()
            elapsed = now - _last_refill
            if elapsed > 0:
                _tokens = min(float(BURST), _tokens + elapsed * QPS)
                _last_refill = now
            if _tokens >= 1:
                _tokens -= 1
                return
            wait_time = max((1 - _tokens) / QPS, 0.01)
            _bucket_lock.release()
            try:
                time.sleep(wait_time)
            finally:
                _bucket_lock.acquire()


def _sync_time() -> None:
    """Update local time offset using ``/api/v3/time``."""
    global _time_offset_ms
    with _time_lock:
        try:
            resp = _session.get(f"{BASE_URL}/api/v3/time", timeout=10)
            resp.raise_for_status()
            server_time = int(resp.json().get("serverTime", 0))
            _time_offset_ms = server_time - now_ms()
            LOGGER.debug("Time synced with Binance; offset=%s ms", _time_offset_ms)
        except Exception as exc:  # pragma: no cover - network errors
            LOGGER.warning("Unable to sync time with Binance: %s", exc)
            _time_offset_ms = 0


def _timestamp() -> int:
    return now_ms() + _time_offset_ms


def _sign(params: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    payload = params.copy()
    payload.setdefault("recvWindow", RECV_WINDOW_MS)
    payload["timestamp"] = _timestamp()
    ordered = [(k, payload[k]) for k in sorted(payload)]
    query = urlencode(ordered, doseq=True)
    signature = hmac_sha256(query)
    payload["signature"] = signature
    return payload, query


def hmac_sha256(message: str) -> str:
    import hmac
    import hashlib

    return hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


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
    return str(from_asset).upper(), str(to_asset).upper()


def _try_cache_response(path: str, params: Dict[str, Any]) -> Optional[Response]:
    key = _cache_key(path, params)
    if not key:
        return None
    cached = _exchange_cache.get(key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at < time.time():
        _exchange_cache.pop(key, None)
        return None
    LOGGER.debug("exchangeInfo cache hit for %s/%s", *key)
    return _build_response(path, payload)


def _store_cache(path: str, params: Dict[str, Any], data: Dict[str, Any]) -> None:
    key = _cache_key(path, params)
    if not key:
        return
    _exchange_cache[key] = (time.time() + EXINFO_TTL_SEC, data)


def _build_response(path: str, data: Dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(data).encode("utf-8")
    resp.headers["Content-Type"] = "application/json"
    resp.url = f"{BASE_URL}{path}"
    resp.encoding = "utf-8"
    return resp


def _backoff_delay(attempt: int) -> float:
    base = min(2 ** (attempt - 1), 16)
    return base + random.uniform(0, 0.25)


def _request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    as_body: bool = True,
) -> Response:
    params = params or {}

    cached = _try_cache_response(path, params)
    if cached is not None:
        return cached

    url = f"{BASE_URL}{path}"
    attempt = 0
    clock_retry = False

    while True:
        attempt += 1
        payload, _ = _sign(params)
        headers = _headers()
        LOGGER.debug("HTTP %s %s params=%s", method, path, {k: v for k, v in params.items() if k != "signature"})
        _acquire_token()
        try:
            if method == "GET":
                response = _session.get(url, params=payload, headers=headers, timeout=10)
            else:
                if as_body:
                    response = _session.post(url, data=payload, headers=headers, timeout=10)
                else:
                    response = _session.post(url, params=payload, headers=headers, timeout=10)
        except requests.RequestException as exc:
            LOGGER.warning("Request error %s %s attempt=%s: %s", method, path, attempt, exc)
            if attempt >= MAX_BACKOFF_ATTEMPTS:
                raise
            time.sleep(_backoff_delay(attempt))
            continue

        data: Optional[Dict[str, Any]] = None
        try:
            data = response.json()
        except ValueError:
            data = None

        if response.status_code == 200 and isinstance(data, dict) and data.get("code") == -1021:
            if not clock_retry:
                clock_retry = True
                LOGGER.warning("Timestamp drift detected; resyncing time")
                _sync_time()
                continue

        if response.status_code == 200:
            if isinstance(data, dict):
                _store_cache(path, params, data)
            LOGGER.debug("HTTP %s %s OK", method, path)
            return response

        rate_limited = response.status_code == 429 or (
            isinstance(data, dict) and data.get("code") in {-1003, 429}
        )
        if rate_limited and attempt < MAX_BACKOFF_ATTEMPTS:
            delay = _backoff_delay(attempt)
            LOGGER.warning(
                "Rate limit hit on %s %s (attempt %s), backing off %.2fs", method, path, attempt, delay
            )
            time.sleep(delay)
            continue

        if isinstance(data, dict) and data.get("code") == -1021 and not clock_retry:
            clock_retry = True
            LOGGER.warning("Timestamp error received; attempting to resync")
            _sync_time()
            continue

        if attempt >= MAX_BACKOFF_ATTEMPTS:
            LOGGER.error(
                "Request failed after %s attempts: %s %s status=%s body=%s",
                attempt,
                method,
                path,
                response.status_code,
                data,
            )
            response.raise_for_status()
            return response

        delay = _backoff_delay(attempt)
        LOGGER.warning(
            "Retrying %s %s (status %s) in %.2fs", method, path, response.status_code, delay
        )
        time.sleep(delay)


def get(path: str, params: Optional[Dict[str, Any]] = None) -> Response:
    """Perform a signed GET request."""
    return _request("GET", path, params=params, as_body=False)


def post(path: str, params: Optional[Dict[str, Any]] = None, *, as_body: bool = True) -> Response:
    """Perform a signed POST request."""
    return _request("POST", path, params=params, as_body=as_body)
