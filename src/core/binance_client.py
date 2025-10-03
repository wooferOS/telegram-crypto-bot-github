from __future__ import annotations
import time, hmac, hashlib, requests
from urllib.parse import urlencode
import config_dev3 as config

API_KEY    = getattr(config, "BINANCE_API_KEY", "")
API_SECRET = getattr(config, "BINANCE_API_SECRET", "")
BASE_URL   = getattr(config, "BINANCE_API_BASE", "https://api.binance.com").rstrip("/")
RECV_WIN   = int(getattr(config, "RECV_WINDOW_MS", 5000))

def _headers() -> dict:
    return {"X-MBX-APIKEY": API_KEY} if API_KEY else {}

def _sign(params: dict) -> dict:
    if not API_SECRET:
        raise RuntimeError("BINANCE_API_SECRET missing in config_dev3.py")
    params = dict(params or {})
    params.setdefault("timestamp", int(time.time() * 1000))
    params.setdefault("recvWindow", RECV_WIN)
    q = urlencode(params, doseq=True)
    sig = hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params

def public_get(path: str, params=None, timeout=10):
    url = BASE_URL + path
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def get(path: str, params=None, signed=False, timeout=10):
    url = BASE_URL + path
    params = dict(params or {})
    if signed:
        params = _sign(params)
    r = requests.get(url, params=params, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r.json()


def post(path: str, params=None, signed=False, timeout=10):
    url = BASE_URL + path
    data = dict(params or {})
    if signed:
        data = _sign(data)
    r = requests.post(url, data=data, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_convert_exchange_info(from_asset: str, to_asset: str, timeout=10):
    """SIGNED /sapi/v1/convert/exchangeInfo (нормалізовано під наш convert_api)."""
    params = {"fromAsset": (from_asset or '').upper(), "toAsset": (to_asset or '').upper()}
    return get("/sapi/v1/convert/exchangeInfo", params, signed=True, timeout=timeout)

def public_ticker_24hr(symbol: str | None = None, timeout=10):
    """GET /api/v3/ticker/24hr
    - якщо symbol заданий -> dict по конкретному символу
    - якщо None -> list по всіх символах
    """
    symbol = (symbol or "").upper()
    params = {"symbol": symbol} if symbol else {}
    return public_get("/api/v3/ticker/24hr", params, timeout=timeout)

def public_book_ticker(symbol: str, timeout=10):
    """GET /api/v3/ticker/bookTicker?symbol=BTCUSDT"""
    symbol = (symbol or "").upper()
    return public_get("/api/v3/ticker/bookTicker", {"symbol": symbol}, timeout=timeout)

def public_ticker_24hr_all(timeout=10):
    return public_ticker_24hr(None, timeout=timeout)
