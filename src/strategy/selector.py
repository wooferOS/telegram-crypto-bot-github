"""Rule-based candidate selection for the auto-cycle."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List

from config_dev3 import ROUTE_WHITELIST
from src.core import balance

LOGGER = logging.getLogger(__name__)


@dataclass
class Route:
    source: str
    target: str
    wallet: str
    amount: str
    regions: Iterable[str]
    priority: int


def _parse_routes(region: str) -> List[Route]:
    routes: List[Route] = []
    for entry in ROUTE_WHITELIST:
        allowed_regions = entry.get("regions") or ["asia", "us"]
        if region not in [r.lower() for r in allowed_regions]:
            continue
        routes.append(
            Route(
                source=str(entry["from"]).upper(),
                target=str(entry["to"]).upper(),
                wallet=str(entry.get("wallet", "SPOT")).upper(),
                amount=str(entry.get("amount", "ALL")),
                regions=allowed_regions,
                priority=int(entry.get("priority", 100)),
            )
        )
    return routes


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

    region = region.lower()
    candidates: List[Dict[str, str]] = []

    for route in sorted(_parse_routes(region), key=lambda item: item.priority):
        if not _has_balance(route.source, route.wallet):
            LOGGER.info(
                "Skipping %s -> %s (%s); zero balance", route.source, route.target, route.wallet
            )
            continue
        candidates.append(
            {
                "from": route.source,
                "to": route.target,
                "wallet": route.wallet,
                "amount": route.amount,
                "priority": route.priority,
            }
        )

    LOGGER.info("Selected %s candidate(s) for %s", len(candidates), region)
    return candidates
