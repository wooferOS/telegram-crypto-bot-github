"""Rule-based candidate selection for the auto-cycle."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List

from src.core import balance

LOGGER = logging.getLogger(__name__)


def _has_balance(asset: str, wallet: str) -> bool:
    try:
        available = balance.read_free(asset, wallet)
        LOGGER.debug("Balance check %s %s -> %s", wallet, asset, available)
        return available > Decimal("0")
    except Exception as exc:  # pragma: no cover - network dependent
        LOGGER.warning("Failed to read %s balance for %s: %s", wallet, asset, exc)
        return False


def build_plan(region: str) -> List[Dict[str, str]]:
    """Return ordered list of conversion candidates for the region."""
    # Basic whitelist rules. They are independent of the region for now but the
    # structure allows region-specific logic later.
    candidates: List[Dict[str, str]] = []

    if _has_balance("ZKC", "SPOT"):
        candidates.append(
            {
                "from": "ZKC",
                "to": "USDT",
                "wallet": "SPOT",
                "amount": "ALL",
                "priority": 1,
            }
        )

    if _has_balance("USDT", "SPOT"):
        candidates.append(
            {
                "from": "USDT",
                "to": "BTC",
                "wallet": "SPOT",
                "amount": "ALL",
                "priority": 2,
            }
        )

    if _has_balance("USDT", "FUNDING"):
        candidates.append(
            {
                "from": "USDT",
                "to": "BTC",
                "wallet": "FUNDING",
                "amount": "ALL",
                "priority": 3,
            }
        )

    candidates.sort(key=lambda item: item.get("priority", 100))
    LOGGER.info("Selected %s candidate(s) for %s", len(candidates), region)
    return candidates
