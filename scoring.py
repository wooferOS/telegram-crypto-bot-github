"""Composite scoring model for Convert pairs.

The score combines edge versus a Spot mid reference with soft penalties for
spread and volatility as well as liquidity and momentum incentives.

``edge = (quote_ratio - mid_ref) / mid_ref``

The final score is computed as::

    S = w1*edge + w2*liquidity + w3*momentum - w4*spread - w5*volatility

Weight parameters are provided by :mod:`config_dev3` via ``SCORING_WEIGHTS``.
"""

from __future__ import annotations

from typing import Dict

import config_dev3
# === ensure default scoring weights ===
try:
    _w = getattr(config_dev3, 'SCORING_WEIGHTS', None)
    if not isinstance(_w, dict):
        config_dev3.SCORING_WEIGHTS = {'edge': 1.0}
    else:
        config_dev3.SCORING_WEIGHTS.setdefault('edge', 1.0)
except Exception:
    try:
        config_dev3.SCORING_WEIGHTS = {'edge': 1.0}
    except Exception:
        pass

import md_rest
import mid_ref


def score_pair(from_asset: str, to_asset: str, quote_ratio: float) -> Dict[str, float] | None:
    """Return score components for the pair.

    All REST market data is fetched via :mod:`md_rest`. Any missing piece simply
    defaults to ``0`` so that the function never raises due to bad data.
    """

    mid, symbol = mid_ref.get_mid_price(from_asset, to_asset, with_symbol=True)
    if not mid:
        return None

    edge = (quote_ratio - mid) / mid

    bt = md_rest.book_ticker(symbol) or {}
    try:
        bid = float(bt.get("bidPrice", 0))
        ask = float(bt.get("askPrice", 0))
        spread = (ask - bid) / mid if bid > 0 and ask > 0 else 0.0
    except Exception:
        spread = 0.0

    t24 = md_rest.ticker_24hr(symbol) or {}
    try:
        liquidity = float(t24.get("quoteVolume", 0))
        trades = float(t24.get("count", 0))
        liquidity = liquidity / 1_000_000 + trades / 10_000
    except Exception:
        liquidity = 0.0

    kl = md_rest.klines(symbol, "1m", limit=2) or []
    try:
        if len(kl) >= 2:
            open_p = float(kl[-2][1])
            close_p = float(kl[-1][4])
            high = float(kl[-1][2])
            low = float(kl[-1][3])
            momentum = (close_p - open_p) / open_p if open_p else 0.0
            volatility = (high - low) / mid if mid else 0.0
        else:
            momentum = 0.0
            volatility = 0.0
    except Exception:
        momentum = 0.0
        volatility = 0.0

    w = config_dev3.SCORING_WEIGHTS
    score = (
        w.get('edge', 1.0) * edge
        + w.get('liquidity', 0.0) * liquidity
        + w.get('momentum', 0.0) * momentum
        - w.get('spread', 0.0) * spread
        - w.get('volatility', 0.0) * volatility
    )

    return {
        "symbol": symbol,
        "mid": mid,
        "edge": edge,
        "liquidity": liquidity,
        "momentum": momentum,
        "spread": spread,
        "volatility": volatility,
        "score": score,
    }
