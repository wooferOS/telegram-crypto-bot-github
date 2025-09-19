"""Route selection for analyze/trade phases."""

from __future__ import annotations

from typing import Dict, List

from config_dev3 import ROUTES_WHITELIST


def _normalize_route(entry: Dict[str, str]) -> Dict[str, str]:
    return {
        "from": str(entry.get("from", "")).upper(),
        "to": str(entry.get("to", "")).upper(),
        "wallet": str(entry.get("wallet", "SPOT")).upper(),
        "amount": str(entry.get("amount", "ALL")),
    }


def select_routes_for_phase(region: str, phase: str) -> List[Dict[str, str]]:
    """Return whitelisted routes for ``region`` and ``phase``."""

    region = region.lower()
    phase = phase.lower()
    routes: List[Dict[str, str]] = []

    for raw in ROUTES_WHITELIST:
        regions = [str(item).lower() for item in raw.get("regions", ["asia", "us"])]
        phases = [str(item).lower() for item in raw.get("phases", ["analyze", "trade"])]
        if region not in regions:
            continue
        if phase not in phases:
            continue
        routes.append(_normalize_route(raw))

    return routes
