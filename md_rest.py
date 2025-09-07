"""Utility wrappers for Binance Spot public REST market data.

All requests use https://data-api.binance.vision and consume official
request weights. These helpers are intentionally light-weight and rely on
:mod:`requests` which is already used elsewhere in the project.

Each function includes a reference to the relevant Binance documentation.
"""

from __future__ import annotations

import requests
from typing import Any, Dict, List

from quote_counter import record_weight

BASE_URL = "https://data-api.binance.vision"

# --- basic REST helpers ----------------------------------------------------

def _get(path: str, params: Dict[str, Any]) -> Dict[str, Any] | None:
    """Perform a GET request against ``BASE_URL``.

    Returns ``None`` on HTTP or JSON decode errors. A small timeout is used to
    avoid hanging the convert cycle.
    """

    try:
        resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


# --- individual endpoints --------------------------------------------------

# https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#current-average-price

def avg_price(symbol: str) -> Dict[str, Any] | None:
    """Return data from ``GET /api/v3/avgPrice`` (weight **2**)."""

    record_weight("avgPrice")
    return _get("/api/v3/avgPrice", {"symbol": symbol})


# https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#symbol-price-ticker

def ticker_price(symbol: str) -> Dict[str, Any] | None:
    """Return data from ``GET /api/v3/ticker/price`` (weight **2**)."""

    record_weight("ticker/price")
    return _get("/api/v3/ticker/price", {"symbol": symbol})


# https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#symbol-order-book-ticker

def book_ticker(symbol: str) -> Dict[str, Any] | None:
    """Return data from ``GET /api/v3/ticker/bookTicker`` (weight **2**)."""

    record_weight("bookTicker")
    return _get("/api/v3/ticker/bookTicker", {"symbol": symbol})


# https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#24hr-ticker-price-change-statistics

def ticker_24hr(symbol: str) -> Dict[str, Any] | None:
    """Return data from ``GET /api/v3/ticker/24hr`` (weight **40**)."""

    record_weight("ticker/24hr")
    return _get("/api/v3/ticker/24hr", {"symbol": symbol})


# https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#klinecandlestick-data

def klines(symbol: str, interval: str, limit: int = 500) -> List[List[Any]] | None:
    """Return ``GET /api/v3/klines`` (weight **2**).

    ``interval`` follows the Binance kline interval spec, e.g. ``"1m"``.
    """

    record_weight("klines")
    return _get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})


# Convenience mid price helper ----------------------------------------------

def mid_price(symbol: str) -> float | None:
    """Return mid price for ``symbol`` using bookTicker then avgPrice.

    The book ticker provides best bid/ask; if either side is missing the
    function falls back to the average price endpoint.
    """

    data = book_ticker(symbol)
    if data:
        try:
            bid = float(data.get("bidPrice", 0))
            ask = float(data.get("askPrice", 0))
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
        except Exception:
            pass
    data = avg_price(symbol)
    if data:
        try:
            px = float(data.get("price", 0))
            if px > 0:
                return px
        except Exception:
            pass
    return None
