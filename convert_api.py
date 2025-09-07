"""Minimal Binance Convert API client for DEV7.

Implements official endpoints as per Binance documentation:
https://developers.binance.com/docs/convert

The functions handle HMAC SHA256 signing with ``timestamp`` and ``recvWindow``
parameters. A simple retry is performed for error ``-1021`` (time sync).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode
from typing import Any, Dict, Optional

import requests

from config_dev3 import BINANCE_API_KEY, BINANCE_API_SECRET

BASE_URL = "https://api.binance.com"
RECV_WINDOW = 5000  # milliseconds


def _sign(params: Dict[str, Any]) -> str:
    query = urlencode(sorted(params.items()))
    return hmac.new(BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()


def _request(method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Any:
    params = params.copy() if params else {}
    headers = {}
    if signed:
        params.setdefault("timestamp", int(time.time() * 1000))
        params.setdefault("recvWindow", RECV_WINDOW)
        params["signature"] = _sign(params)
        headers["X-MBX-APIKEY"] = BINANCE_API_KEY
    url = f"{BASE_URL}{path}"
    response = requests.request(method, url, params=params, headers=headers, timeout=10)
    data = response.json()
    # simple retry for -1021: Timestamp for this request is outside of the recvWindow.
    if data.get("code") == -1021 and signed:
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = _sign(params)
        response = requests.request(method, url, params=params, headers=headers, timeout=10)
        data = response.json()
    return data


def get_exchange_info() -> Any:
    """List all convert pairs and limits.

    Endpoint: ``GET /sapi/v1/convert/exchangeInfo``
    Weight: 3000/IP
    """
    return _request("GET", "/sapi/v1/convert/exchangeInfo")


def get_asset_info() -> Any:
    """Query precision per asset.

    Endpoint: ``GET /sapi/v1/convert/assetInfo`` (USER_DATA)
    Weight: 100/IP
    """
    return _request("GET", "/sapi/v1/convert/assetInfo", signed=True)


def get_quote(from_asset: str, to_asset: str, amount: float, wallet: str = "SPOT") -> Any:
    """Send quote request.

    Endpoint: ``POST /sapi/v1/convert/getQuote``
    Weight: 200/UID
    """
    params = {
        "fromAsset": from_asset,
        "toAsset": to_asset,
        "fromAmount": amount,
        "walletType": wallet,
    }
    return _request("POST", "/sapi/v1/convert/getQuote", params, signed=True)


def accept_quote(quote_id: str) -> Any:
    """Accept previously obtained quote.

    Endpoint: ``POST /sapi/v1/convert/acceptQuote``
    Weight: 500/UID
    """
    params = {"quoteId": quote_id}
    return _request("POST", "/sapi/v1/convert/acceptQuote", params, signed=True)


def order_status(order_id: Optional[str] = None, quote_id: Optional[str] = None) -> Any:
    """Query order status by ``orderId`` or ``quoteId``.

    Endpoint: ``GET /sapi/v1/convert/orderStatus``
    Weight: 100/UID
    """
    params: Dict[str, Any] = {}
    if order_id:
        params["orderId"] = order_id
    if quote_id:
        params["quoteId"] = quote_id
    return _request("GET", "/sapi/v1/convert/orderStatus", params, signed=True)


def trade_flow(start_time: int, end_time: int) -> Any:
    """Get convert trade history for a period (<=30 days).

    Endpoint: ``GET /sapi/v1/convert/tradeFlow``
    Weight: 3000/UID
    """
    params = {"startTime": start_time, "endTime": end_time}
    return _request("GET", "/sapi/v1/convert/tradeFlow", params, signed=True)


__all__ = [
    "get_exchange_info",
    "get_asset_info",
    "get_quote",
    "accept_quote",
    "order_status",
    "trade_flow",
]
