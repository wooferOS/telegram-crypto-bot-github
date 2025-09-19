"""Helpers for reading SPOT and FUNDING balances."""
from __future__ import annotations

from decimal import Decimal
import logging
import time
from typing import Dict, Iterable, Tuple

from src.core import binance_client

LOGGER = logging.getLogger(__name__)

_CACHE_TTL = 10.0
_spot_cache: Tuple[float, Dict[str, Decimal]] | None = None
_funding_cache: Tuple[float, Dict[str, Decimal]] | None = None


def _now() -> float:
    return time.monotonic()


def _parse_assets(payload: Iterable[Dict[str, str]]) -> Dict[str, Decimal]:
    balances: Dict[str, Decimal] = {}
    for entry in payload:
        asset = entry.get("asset")
        free = entry.get("free", "0")
        if asset is None:
            continue
        try:
            balances[str(asset)] = Decimal(str(free))
        except Exception:  # pragma: no cover - defensive parsing
            LOGGER.debug("Skipping malformed balance entry: %s", entry)
    return balances


def _read_spot_balances(force: bool = False) -> Dict[str, Decimal]:
    global _spot_cache
    if not force and _spot_cache is not None:
        ts, data = _spot_cache
        if _now() - ts < _CACHE_TTL:
            return data

    response = binance_client.get("/api/v3/account", params={})
    payload = response.json() if response.content else {}
    balances = payload.get("balances") if isinstance(payload, dict) else None
    if isinstance(balances, list):
        data = _parse_assets(balances)  # type: ignore[arg-type]
    else:
        data = {}
    _spot_cache = (_now(), data)
    return data


def _read_funding_balances(force: bool = False) -> Dict[str, Decimal]:
    global _funding_cache
    if not force and _funding_cache is not None:
        ts, data = _funding_cache
        if _now() - ts < _CACHE_TTL:
            return data

    response = binance_client.post(
        "/sapi/v3/asset/getUserAsset",
        params={"needBtcValuation": False},
    )
    payload = response.json() if response.content else {}
    entries: Iterable[Dict[str, str]]
    if isinstance(payload, list):
        entries = payload  # type: ignore[assignment]
    elif isinstance(payload, dict):
        entries = payload.get("assets", [])  # type: ignore[assignment]
    else:  # pragma: no cover - defensive
        entries = []
    data = _parse_assets(entries)
    _funding_cache = (_now(), data)
    return data


def read_free_spot(asset: str) -> Decimal:
    """Read free balance for ``asset`` from the SPOT wallet."""

    return _read_spot_balances().get(asset.upper(), Decimal("0"))


def read_free_funding(asset: str) -> Decimal:
    """Read free balance for ``asset`` from the FUNDING wallet."""

    return _read_funding_balances().get(asset.upper(), Decimal("0"))


def read_free(asset: str, wallet: str) -> Decimal:
    """Return the free balance for ``asset`` in the selected ``wallet``."""

    wallet = wallet.upper()
    if wallet == "FUNDING":
        return read_free_funding(asset)
    return read_free_spot(asset)
