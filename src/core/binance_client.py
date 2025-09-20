import time
import hmac
import hashlib
import threading
from urllib.parse import urlencode
from typing import Any, Dict, Optional

import requests

# Єдиний імпорт налаштувань з локального файлу (НЕ комітиться)
from config_dev3 import (
    BINANCE_API_KEY,
    BINANCE_SECRET_KEY,
    BASE,
    RECV_WINDOW_MS,
    REQUEST_TIMEOUT,
    QPS,
    BURST,
    BACKOFF_MAX_RETRIES,
    BACKOFF_BASE_S,
    BACKOFF_MAX_S,
    EXCHANGEINFO_TTL_SEC,
)

# Глобальна HTTP-сесія
session = requests.Session()
session.headers.update({"X-MBX-APIKEY": BINANCE_API_KEY})

# ---------------- token bucket (проти спаму) ----------------
_tokens = BURST
_last_refill = time.monotonic()
_bucket_lock = threading.Lock()

def _take_token():
    global _tokens, _last_refill
    with _bucket_lock:
        now = time.monotonic()
        # поповнення
        refill = (now - _last_refill) * QPS
        if refill >= 1.0:
            _tokens = min(BURST, _tokens + int(refill))
            _last_refill = now
        # чекати, якщо порожньо
        while _tokens <= 0:
            sleep_for = max(0.001, 1.0 / QPS)
            _bucket_lock.release()
            try:
                time.sleep(sleep_for)
            finally:
                _bucket_lock.acquire()
            now = time.monotonic()
            refill = (now - _last_refill) * QPS
            if refill >= 1.0:
                _tokens = min(BURST, _tokens + int(refill))
                _last_refill = now
        _tokens -= 1

# ---------------- допоміжні ----------------
def _now_ms() -> int:
    return int(time.time() * 1000)

def _sign_qs(params: Dict[str, Any]) -> str:
    # тільки не-None і без дублювань
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    qs = urlencode(clean, doseq=True)
    sig = hmac.new(BINANCE_SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return f"{qs}&signature={sig}"

def _request(method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = True):
    """
    Єдина точка доступу.
    Для SAPI підписаних ендпоінтів (Convert) — ВСЕ в query string:
      - ...&timestamp=...&recvWindow=...
      - signature=HMAC_SHA256(secret, query_string)
    Тіло (json/data) — порожнє.
    Доки: https://binance-docs.github.io/apidocs/spot/en/#convert-endpoints
    """
    _take_token()
    url = BASE.rstrip("/") + path

    p = dict(params or {})
    if signed:
        p.setdefault("timestamp", _now_ms())
        p.setdefault("recvWindow", RECV_WINDOW_MS)
        query = _sign_qs(p)
    else:
        query = urlencode({k: v for k, v in p.items() if v is not None})

    # повний URL з query
    if query:
        url = f"{url}?{query}"

    # ретраї на 429/-1003/-1021 та тимчасові 5xx
    backoff = BACKOFF_BASE_S
    for attempt in range(1, BACKOFF_MAX_RETRIES + 1):
        try:
            resp = session.request(method, url, timeout=REQUEST_TIMEOUT)
            code = None
            try:
                js = resp.json()
                code = js.get("code")
            except Exception:
                js = None

            # нормальні кейси
            if resp.ok and (js is None or "code" not in js or (isinstance(code, int) and code == 0)):
                return js if js is not None else resp.json()

            # помилки, які має сенс ретраїти
            retryable = resp.status_code in (429, 418, 500, 502, 503, 504) or code in (-1003, -1021)
            if retryable and attempt < BACKOFF_MAX_RETRIES:
                time.sleep(min(backoff, BACKOFF_MAX_S))
                backoff *= 2
                continue

            # віддати як є (підніме вищі рівні)
            resp.raise_for_status()
        except requests.RequestException as e:
            if attempt < BACKOFF_MAX_RETRIES:
                time.sleep(min(backoff, BACKOFF_MAX_S))
                backoff *= 2
                continue
            raise e

# ---------------- публічні обгортки ----------------

# Кеш exchangeInfo (щоб не лупити кожен раз)
_exinfo_cache: Dict[str, Any] = {}
_exinfo_expire_at = 0.0
_exinfo_lock = threading.Lock()

def get(path: str, params: Optional[Dict[str, Any]] = None, signed: bool = True):
    return _request("GET", path, params, signed=signed)

def post(path: str, params: Optional[Dict[str, Any]] = None, signed: bool = True):
    return _request("POST", path, params, signed=signed)

def get_convert_exchange_info(from_asset: str, to_asset: str) -> Dict[str, Any]:
    """
    GET /sapi/v1/convert/exchangeInfo (SIGNED)
    https://binance-docs.github.io/apidocs/spot/en/#get-convert-asset-info-user_data
    """
    now = time.monotonic()
    key = f"{from_asset}_{to_asset}"
    with _exinfo_lock:
        global _exinfo_expire_at
        if now < _exinfo_expire_at and key in _exinfo_cache:
            return _exinfo_cache[key]

    data = get("/sapi/v1/convert/exchangeInfo", {"fromAsset": from_asset, "toAsset": to_asset}, signed=True)
    with _exinfo_lock:
        _exinfo_cache[key] = data
        _exinfo_expire_at = time.monotonic() + EXCHANGEINFO_TTL_SEC
    return data
