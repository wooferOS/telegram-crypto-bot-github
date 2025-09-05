from decimal import Decimal
import requests


def load_symbol_filters(base_asset: str, quote_asset: str = "USDT"):
    """Return LOT_SIZE.stepSize and MIN_NOTIONAL.minNotional for a symbol.

    If the pair does not exist, returns ``(None, None)`` and logs should warn.
    """
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/exchangeInfo", timeout=10
        )
        data = resp.json()
    except Exception:  # pragma: no cover - network/IO
        return None, None

    for s in data.get("symbols", []):
        if s.get("baseAsset") == base_asset and s.get("quoteAsset") == quote_asset:
            step = Decimal("0")
            min_n = Decimal("0")
            for f in s.get("filters", []):
                if f.get("filterType") == "LOT_SIZE":
                    step = Decimal(str(f.get("stepSize", "0")))
                elif f.get("filterType") == "MIN_NOTIONAL":
                    min_n = Decimal(str(f.get("minNotional", "0")))
            return step, min_n
    return None, None


def get_last_price_usdt(asset: str):
    """Return last price of ASSETUSDT pair as Decimal or ``None`` if missing."""
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": f"{asset}USDT"},
            timeout=10,
        )
    except Exception:  # pragma: no cover - network/IO
        return None
    if r.status_code == 200:
        try:
            return Decimal(r.json()["price"])
        except Exception:  # pragma: no cover
            return None
    return None
