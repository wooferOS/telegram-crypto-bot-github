from __future__ import annotations
from typing import Dict, Any, Generator, List
from config_dev3 import ROUTES_WHITELIST
from src.core import balance

def iter_whitelist() -> Generator[Dict[str, Any], None, None]:
    for raw in (ROUTES_WHITELIST or []):
        fa = (raw.get("from") or raw.get("from_asset") or "").upper().strip()
        ta = (raw.get("to")   or raw.get("to_asset")   or "").upper().strip()
        wallet = (raw.get("wallet") or "SPOT").upper().strip()
        amt = raw.get("amount", 0)
        if not fa or not ta:
            continue
        if isinstance(amt, str) and amt.strip().upper() == "ALL":
            try:
                free = balance.read_free(fa, wallet) or 0
            except Exception:
                free = 0
            try:
                amt = float(free)
            except Exception:
                amt = 0.0
        else:
            try:
                amt = float(amt)
            except Exception:
                amt = 0.0
        if amt <= 0:
            continue
        yield {"from": fa, "to": ta, "wallet": wallet, "amount": amt}

def select_routes_for_phase(region: str, phase: str) -> List[Dict[str, Any]]:
    return list(iter_whitelist())
