from __future__ import annotations
import hashlib
import hmac
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode
import requests
import config_dev3 as config  # очікуємо BINANCE_API_KEY, BINANCE_API_SECRET, опц. BINANCE_BASE_URL, RECV_WINDOW_MS

BASE_URL = getattr(config, "BINANCE_BASE_URL", "https://api.binance.com").rstrip("/")
API_KEY = getattr(config, "BINANCE_API_KEY", "")
API_SECRET_TEXT = getattr(config, "BINANCE_API_SECRET", "")
API_SECRET = API_SECRET_TEXT.encode("utf-8") if isinstance(API_SECRET_TEXT, str) else (API_SECRET_TEXT or b"")

RECV_WINDOW_MS_DEFAULT = int(getattr(config, "RECV_WINDOW_MS", 5000))

session = requests.Session()
if API_KEY:
    session.headers.update({"X-MBX-APIKEY": API_KEY})


def _is_convert(path: str) -> bool:
    return "/sapi/v1/convert/" in (path or "")


def _sign(params: Dict[str, Any]) -> str:
    qs = urlencode(params, doseq=True)
    return hmac.new(API_SECRET, qs.encode("utf-8"), hashlib.sha256).hexdigest()


def _request(method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = True) -> requests.Response:
    if params is None:
        params = {}

    # Додаємо таймштамп і recvWindow для підписаних запитів
    if signed:
        params = dict(params)
        params.setdefault("timestamp", int(time.time() * 1000))
        # Для convert — збільшуємо recvWindow до 60000 за замовчуванням
        if _is_convert(path):
            params.setdefault("recvWindow", 60000)
        else:
            params.setdefault("recvWindow", RECV_WINDOW_MS_DEFAULT)
        params["signature"] = _sign(params)

    url = f"{BASE_URL}{path}"
    resp = session.request(method.upper(), url, params=params, timeout=15)
    # Нехай піднімає HTTPError при 4xx/5xx — верхній рівень уже логгує
    resp.raise_for_status()
    return resp


# -------- Публічні ендпоінти --------
def public_ticker_24hr(symbol: Optional[str] = None):
    p: Dict[str, Any] = {}
    if symbol:
        p["symbol"] = symbol
    return _request("GET", "/api/v3/ticker/24hr", p, signed=False).json()


# -------- Convert API (signed) --------
def get_convert_exchange_info(from_asset: str, to_asset: str) -> Dict[str, Any]:
    p = {"fromAsset": (from_asset or "").upper(), "toAsset": (to_asset or "").upper()}
    return _request("GET", "/sapi/v1/convert/exchangeInfo", p, signed=True).json()


def post_convert_get_quote(
    from_asset: str, to_asset: str, from_amount: str, wallet_type: str = "SPOT"
) -> requests.Response:
    p = {
        "fromAsset": (from_asset or "").upper(),
        "toAsset": (to_asset or "").upper(),
        "fromAmount": str(from_amount),
        "walletType": (wallet_type or "SPOT").upper(),
    }
    return _request("POST", "/sapi/v1/convert/getQuote", p, signed=True)


def post_convert_accept_quote(quote_id: str) -> requests.Response:
    p = {"quoteId": quote_id}
    return _request("POST", "/sapi/v1/convert/acceptQuote", p, signed=True)


def get_convert_order_status(order_id: Optional[str] = None, quote_id: Optional[str] = None) -> Dict[str, Any]:
    p: Dict[str, Any] = {}
    if order_id:
        p["orderId"] = order_id
    if quote_id:
        p["quoteId"] = quote_id
    return _request("GET", "/sapi/v1/convert/orderStatus", p, signed=True).json()
