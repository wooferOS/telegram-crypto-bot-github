from decimal import Decimal
from typing import Dict
from src.core import binance_client


def _to_decimal(x) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def _read_spot_balances() -> Dict[str, Decimal]:
    """
    SPOT: /sapi/v3/asset/getUserAsset (POST, signed)
    Від Binance може прийти або список [{asset, free, locked, ...}], або dict із полем balances.
    Повертаємо мапу {ASSET -> free: Decimal}.
    """
    payload = binance_client.post("/sapi/v3/asset/getUserAsset", {"needBtcValuation": False}, signed=True)
    balances: Dict[str, Decimal] = {}
    if isinstance(payload, list):
        for it in payload:
            a = (it.get("asset") or "").upper()
            if not a:
                continue
            free = _to_decimal(it.get("free"))
            # тут беремо саме free (не додаємо locked)
            balances[a] = free
    elif isinstance(payload, dict):
        for it in payload.get("balances", []):
            a = (it.get("asset") or "").upper()
            if not a:
                continue
            free = _to_decimal(it.get("free"))
            balances[a] = free
    return balances


def _read_funding_balances() -> Dict[str, Decimal]:
    """
    FUNDING: /sapi/v1/asset/get-funding-asset (POST, signed)
    Часто повертає список з полями {asset, free|amount, ...}.
    """
    payload = binance_client.post("/sapi/v1/asset/get-funding-asset", {}, signed=True)
    balances: Dict[str, Decimal] = {}
    if isinstance(payload, list):
        iters = payload
    else:
        iters = payload.get("assets", []) if isinstance(payload, dict) else []

    for it in iters:
        a = (it.get("asset") or "").upper()
        if not a:
            continue
        # деякі відповіді мають 'amount' замість 'free'
        val = it.get("free", it.get("amount"))
        balances[a] = _to_decimal(val)
    return balances


def read_free_spot(asset: str) -> Decimal:
    return _read_spot_balances().get(asset.upper(), Decimal("0"))


def read_free_funding(asset: str) -> Decimal:
    return _read_funding_balances().get(asset.upper(), Decimal("0"))


def read_free(asset: str, wallet: str | None) -> Decimal:
    w = (wallet or "SPOT").upper()
    if w == "FUNDING":
        return read_free_funding(asset)
    return read_free_spot(asset)


# --- Compatibility shim expected by strategy/selector.py ---
from typing import Dict


def read_all(wallet: str | None = None) -> Dict[str, Decimal]:
    """Return dict(asset -> Decimal free_amount) for the requested wallet.

    Supported wallet values:
      - None or 'SPOT'    -> spot balances
      - 'FUNDING' or 'EARN' (alias) -> funding balances
    """
    w = (wallet or "SPOT").upper()
    if w == "SPOT":
        return _read_spot_balances()
    if w in ("FUNDING", "EARN"):
        return _read_funding_balances()
    # на всяк випадок — невідомий гаманець -> порожньо
    return {}
