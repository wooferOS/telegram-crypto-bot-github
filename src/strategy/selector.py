from __future__ import annotations
import os
from typing import Dict, Any, List, Set
from src.core import balance

def _env_targets() -> List[str]:
    raw = os.environ.get("CONVERT_TARGETS", "").strip()
    if not raw:
        return []
    return [t.strip().upper() for t in raw.split(",") if t.strip()]

def _positive_assets(min_notional: float, wallet: str) -> Dict[str, float]:
    res: Dict[str, float] = {}
    bals = balance.read_all(wallet) or {}
    if isinstance(bals, dict):
        items = bals.items()
    else:
        items = []
    for asset, free in items:
        try:
            f = float(free or 0)
        except Exception:
            f = 0.0
        if f > min_notional:
            res[str(asset).upper()] = f
    return res

def select_routes_for_phase(region: str, phase: str) -> List[Dict[str, Any]]:
    try:
        min_notional = float(os.environ.get("MIN_NOTIONAL", "1.0"))
    except Exception:
        min_notional = 1.0
    wallet = os.environ.get("DEFAULT_WALLET", "SPOT").upper()

    pos = _positive_assets(min_notional, wallet)
    targets_env = _env_targets()

    routes: List[Dict[str, Any]] = []
    assets: List[str] = sorted(pos.keys())
    assets_set: Set[str] = set(assets)

    for fa in assets:
        amount = pos.get(fa, 0.0)
        if amount <= 0:
            continue
        if targets_env:
            tos = [t for t in targets_env if t != fa]
        else:
            tos = [t for t in assets if t != fa]
        for ta in tos:
            routes.append({"from": fa, "to": ta, "wallet": wallet, "amount": amount})
    return routes
