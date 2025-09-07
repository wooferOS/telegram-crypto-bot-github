"""Binance helper utilities for DEV7.

Only contains balance helpers required for Convert flow; spot trading is intentionally
absent. The get_token_balance function is resilient and safe to call in PAPER/DRY_RUN
modes where client may be None or API unavailable.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_token_balance(client: Optional[object], asset: str, wallet: str = "SPOT") -> float:
    """Return available balance for an asset.

    Parameters
    ----------
    client: Optional object with ``get_asset_balance`` method (Binance client)
    asset:  Asset symbol, e.g. ``"BTC"``
    wallet: Wallet type, currently only ``"SPOT"`` is used

    Returns
    -------
    float
        Free amount of the asset or ``0.0`` on any failure. All exceptions are
        caught and logged to avoid breaking PAPER/DRY_RUN executions.
    """

    if client is None:
        logger.warning("get_token_balance called without client: %s", asset)
        return 0.0
    try:
        bal = client.get_asset_balance(asset=asset)
        free = bal.get("free")  # type: ignore[union-attr]
        return float(free or 0.0)
    except Exception as exc:  # pragma: no cover - network/SDK errors
        logger.warning(
            "❌ get_token_balance fallback: %s wallet=%s err=%s", asset, wallet, exc
        )
        return 0.0
