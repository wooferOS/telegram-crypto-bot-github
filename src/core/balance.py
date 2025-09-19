"""Helpers for reading SPOT and FUNDING balances."""
from __future__ import annotations

from decimal import Decimal

from src.core import binance_client


def read_spot_free(asset: str) -> Decimal:
    response = binance_client.get("/api/v3/account")
    payload = response.json()
    if isinstance(payload, dict):
        balances = payload.get("balances", [])
        if isinstance(balances, list):
            for entry in balances:
                if entry.get("asset") == asset:
                    return Decimal(entry.get("free", "0"))
    return Decimal("0")


def read_funding_free(asset: str) -> Decimal:
    response = binance_client.post(
        "/sapi/v3/asset/getUserAsset", {"asset": asset}
    )
    payload = response.json()
    if isinstance(payload, list):
        for entry in payload:
            if entry.get("asset") == asset:
                return Decimal(entry.get("free", "0"))
    elif isinstance(payload, dict):
        # some responses wrap the list under "assets"
        entries = payload.get("assets", [])
        if isinstance(entries, list):
            for entry in entries:
                if entry.get("asset") == asset:
                    return Decimal(entry.get("free", "0"))
    return Decimal("0")


def read_free(asset: str, wallet: str) -> Decimal:
    wallet = wallet.upper()
    if wallet == "FUNDING":
        return read_funding_free(asset)
    return read_spot_free(asset)
