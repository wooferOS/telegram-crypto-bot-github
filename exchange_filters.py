from decimal import Decimal
from typing import Optional, Tuple

import requests

import convert_api


def load_symbol_filters(
    base_asset: str, quote_asset: str = "USDT"
) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """Return step size and minimum from-amount for a Convert pair."""

    try:
        info = convert_api.exchange_info(fromAsset=base_asset)  # Convert exchangeInfo
        if isinstance(info, dict):
            for item in info.get("toAssetList", []):
                if item.get("toAsset") == quote_asset:
                    min_from = Decimal(str(item.get("fromAssetMinAmount", "0")))
                    asset_meta = convert_api.asset_info(base_asset)  # Convert assetInfo
                    frac = int(asset_meta.get("fraction", 0))
                    step = (
                        Decimal("1") / (Decimal("10") ** frac) if frac > 0 else Decimal("1")
                    )
                    return step, min_from
    except Exception:  # pragma: no cover - network
        pass
    return None, None


def get_last_price_usdt(asset: str):
    """Return last price of ASSETUSDT pair as Decimal or ``None`` if missing."""
    try:
        r = requests.get(
            "https://data-api.binance.vision/api/v3/ticker/price",
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
