"""Wrappers around Binance Convert endpoints."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from src.core import balance, binance_client
from src.core.utils import ensure_amount_and_limits, floor_str_8

LOGGER = logging.getLogger(__name__)


def get_exchange_info(from_asset: str, to_asset: str) -> Dict[str, Any]:
    """Return exchange limits for the provided pair."""

    response = binance_client.get(
        "/sapi/v1/convert/exchangeInfo",
        {"fromAsset": from_asset.upper(), "toAsset": to_asset.upper()},
    )
    return response.json() if response.content else {}


def _to_decimal(value: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"invalid decimal value {value!r}") from None


def _resolve_amount(from_asset: str, wallet: str, amount_spec: str) -> Decimal:
    if amount_spec.strip().upper() == "ALL":
        return balance.read_free(from_asset, wallet)
    return _to_decimal(amount_spec)


def get_quote(
    from_asset: str,
    to_asset: str,
    from_amount: str,
    wallet: str,
) -> Dict[str, Any]:
    """Request a Convert quote and enrich the payload with context."""

    wallet = wallet.upper()
    from_asset = from_asset.upper()
    to_asset = to_asset.upper()

    exchange_info = get_exchange_info(from_asset, to_asset)
    amount_dec = _resolve_amount(from_asset, wallet, from_amount)
    if amount_dec <= Decimal("0"):
        raise ValueError("amount must be positive")

    ensure_amount_and_limits(exchange_info, amount_dec)

    available = balance.read_free(from_asset, wallet)
    amount_str = floor_str_8(amount_dec)

    response = binance_client.post(
        "/sapi/v1/convert/getQuote",
        {
            "fromAsset": from_asset,
            "toAsset": to_asset,
            "fromAmount": amount_str,
            "walletType": wallet,
        },
    )
    payload = response.json() if response.content else {}
    if not isinstance(payload, dict):
        payload = {"data": payload}

    payload.update(
        {
            "fromAsset": from_asset,
            "toAsset": to_asset,
            "wallet": wallet,
            "requestedAmount": amount_str,
            "requestedAmountDecimal": str(amount_dec),
            "available": str(available),
            "insufficient": amount_dec > available,
            "exchangeInfo": exchange_info,
        }
    )
    return payload


def accept_quote(quote_id: str, wallet: str) -> Dict[str, Any]:
    """Accept a previously obtained quote."""

    wallet = wallet.upper()
    response = binance_client.post(
        "/sapi/v1/convert/acceptQuote",
        {"quoteId": quote_id, "walletType": wallet},
    )
    return response.json() if response.content else {}


def get_order_status(order_id: int | str) -> Dict[str, Any]:
    """Fetch the status of an accepted Convert order."""

    response = binance_client.get(
        "/sapi/v1/convert/orderStatus",
        {"orderId": order_id},
    )
    return response.json() if response.content else {}


def get_trade_flow(start_ms: int, end_ms: int, limit: int = 100) -> Dict[str, Any]:
    """Return trade history for the provided time range."""

    response = binance_client.get(
        "/sapi/v1/convert/tradeFlow",
        {"startTime": start_ms, "endTime": end_ms, "limit": limit},
    )
    return response.json() if response.content else {}
