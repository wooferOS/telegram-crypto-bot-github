import requests
from quote_counter import record_weight, weight_book_ticker
from config_dev3 import MARKETDATA_BASE

BASE_URL = MARKETDATA_BASE


def _get(path: str, params: dict) -> dict | None:
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


def get_mid_price(from_asset: str, to_asset: str) -> float | None:
    symbol = f"{from_asset}{to_asset}"
    params = {"symbol": symbol}
    record_weight("bookTicker", weight_book_ticker(params))
    data = _get("/api/v3/ticker/bookTicker", params)
    if data:
        try:
            bid = float(data.get("bidPrice", 0))
            ask = float(data.get("askPrice", 0))
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
        except Exception:
            pass
    record_weight("avgPrice")
    data = _get("/api/v3/avgPrice", {"symbol": symbol})
    if data:
        try:
            price = float(data.get("price", 0))
            if price > 0:
                return price
        except Exception:
            pass
    return None
