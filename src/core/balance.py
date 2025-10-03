
from __future__ import annotations
import logging
logging.getLogger(__name__).info('balance init: file=%s', __file__)
from decimal import Decimal
import time
from . import binance_client

# Невеликий кеш, щоб не смикати біржу занадто часто
_CACHE = {"ts": 0.0, "spot": {}}
_TTL = 8.0  # секунд

def _fetch_spot_balances() -> dict[str, Decimal]:
    try:
        payload = binance_client.get("/api/v3/account", {}, signed=True)
        bals = payload.get("balances") if isinstance(payload, dict) else None
        res: dict[str, Decimal] = {}
        for it in bals or []:
            a = (it.get("asset") or "").upper()
            free = Decimal(str(it.get("free") or "0"))
            if a:
                res[a] = free
        return res
    except Exception as e:
        from logging import getLogger; getLogger(__name__).warning('account fetch failed: %s', e)
        return None

def read_free(asset: str, wallet: str = "SPOT") -> Decimal:
    asset = (asset or "").upper()
    wallet = (wallet or "SPOT").upper()
    if wallet != "SPOT":
        # FUNDING та інші — додамо окремо за потреби
        return Decimal("0")

    now = time.time()
    if now - _CACHE["ts"] > _TTL or not _CACHE["spot"]:
        resp = _fetch_spot_balances()
        if isinstance(resp, dict):
            _CACHE["spot"] = resp
            _CACHE["ts"] = now
    return _CACHE["spot"].get(asset, Decimal("0"))
