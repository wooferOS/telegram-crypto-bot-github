"""Mapping between Convert pairs and Spot market symbols.

The module derives a reference mid price for a Convert pair using Spot market
prices. It first attempts to use a direct Spot symbol (``FROMTO``). If the
symbol does not exist, a synthetic cross via stablecoins or ``BTC`` is used.

References:
- Convert market data: https://developers.binance.com/docs/convert/market-data
- Spot avgPrice/bookTicker: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
"""

from __future__ import annotations

from typing import List, Tuple

import md_rest

# Candidate bridge assets for synthetic crosses. Order reflects priority
BRIDGE_ASSETS = ["USDT", "USDC", "BUSD", "BTC"]


def _spot_mid(symbol: str) -> float | None:
    return md_rest.mid_price(symbol)


def _direct_symbol(from_asset: str, to_asset: str) -> str:
    return f"{from_asset}{to_asset}".upper()


def get_mid_price(from_asset: str, to_asset: str, *, with_symbol: bool = False) -> Tuple[float | None, str] | float | None:
    """Return Spot mid price for the Convert pair ``from_asset``→``to_asset``.

    If ``with_symbol`` is ``True`` the return value is ``(mid, symbol)``.
    ``symbol`` is the Spot symbol used for the computation (either direct or the
    first leg when synthetic).
    """

    symbol = _direct_symbol(from_asset, to_asset)
    mid = _spot_mid(symbol)
    if mid is not None:
        return (mid, symbol) if with_symbol else mid

    # synthetic via bridges
    for bridge in BRIDGE_ASSETS:
        if bridge in (from_asset, to_asset):
            continue
        leg1 = _spot_mid(_direct_symbol(from_asset, bridge))
        leg2 = _spot_mid(_direct_symbol(to_asset, bridge))
        if leg1 and leg2 and leg2 > 0:
            mid = leg1 / leg2
            return (mid, symbol) if with_symbol else mid
    return (None, symbol) if with_symbol else None
