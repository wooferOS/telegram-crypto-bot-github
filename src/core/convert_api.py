"""Lightweight wrappers around Binance Convert endpoints."""
from __future__ import annotations

# Official documentation references:
# - /sapi/v1/convert/exchangeInfo
# - /sapi/v1/convert/getQuote
# - /sapi/v1/convert/acceptQuote
# - /sapi/v1/convert/orderStatus
# - /sapi/v1/convert/tradeFlow

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Tuple

from src.core import balance, binance_client
from src.core.utils import floor_str_8, sleep_jitter

LOGGER = logging.getLogger(__name__)

_QUOTE_JITTER_MIN_MS = 50
_QUOTE_JITTER_MAX_MS = 150


class ConvertError(RuntimeError):
    """Raised when Convert API pre-checks fail."""


def get_exchange_info(from_asset: str, to_asset: str) -> Dict[str, Any]:
    """Fetch exchange information for the provided pair."""

    response = binance_client.get(
        "/sapi/v1/convert/exchangeInfo",
        {"fromAsset": from_asset.upper(), "toAsset": to_asset.upper()},
    )
    return response.json()


def _extract_limits(info: Dict[str, Any]) -> Tuple[Decimal, Decimal]:
    data = info.get("data") if isinstance(info, dict) else {}
    payload = data if isinstance(data, dict) else info
    min_amount = _to_decimal(payload.get("fromAssetMinAmount"))
    max_amount = _to_decimal(payload.get("fromAssetMaxAmount"))
    return min_amount, max_amount


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):  # pragma: no cover - defensive
        return Decimal("0")


def _resolve_amount(
    from_asset: str,
    wallet: str,
    amount_spec: str,
    *,
    min_amount: Decimal,
    max_amount: Decimal,
) -> Tuple[Decimal, Decimal, str, bool]:
    wallet = wallet.upper()
    available = balance.read_free(from_asset, wallet)

    amount_spec = amount_spec.strip().upper()
    if amount_spec == "ALL":
        amount_dec = available
    else:
        try:
            amount_dec = Decimal(amount_spec)
        except (InvalidOperation, ValueError):
            raise ConvertError(f"invalid amount {amount_spec}") from None

    amount_str = floor_str_8(amount_dec)
    if not amount_str or Decimal(amount_str) <= Decimal("0"):
        raise ConvertError("amount must be positive")

    amount_dec = Decimal(amount_str)
    insufficient = amount_dec > available

    if amount_dec < min_amount:
        raise ConvertError(
            f"amount {amount_dec} below minimum {min_amount}"
        )

    if max_amount > 0 and amount_dec > max_amount:
        raise ConvertError(
            f"amount {amount_dec} above maximum {max_amount}"
        )

    return amount_dec, available, amount_str, insufficient


def get_quote(
    from_asset: str,
    to_asset: str,
    amount_spec: str,
    wallet: str,
) -> Dict[str, Any]:
    """Request a quote for converting ``from_asset`` to ``to_asset``."""

    info = get_exchange_info(from_asset, to_asset)
    min_amount, max_amount = _extract_limits(info)
    amount_dec, available, amount_str, insufficient = _resolve_amount(
        from_asset,
        wallet,
        amount_spec,
        min_amount=min_amount,
        max_amount=max_amount,
    )

    sleep_jitter(_QUOTE_JITTER_MIN_MS, _QUOTE_JITTER_MAX_MS)
    response = binance_client.post(
        "/sapi/v1/convert/getQuote",
        {
            "fromAsset": from_asset.upper(),
            "toAsset": to_asset.upper(),
            "fromAmount": amount_str,
            "walletType": wallet.upper(),
        },
    )
    payload = response.json()
    payload_metadata = {
        "fromAsset": from_asset.upper(),
        "toAsset": to_asset.upper(),
        "amount": amount_str,
        "amountDecimal": str(amount_dec),
        "available": str(available),
        "insufficient": insufficient,
        "minAmount": str(min_amount),
        "maxAmount": str(max_amount),
        "wallet": wallet.upper(),
        "exchangeInfo": info,
    }
    if isinstance(payload, dict):
        payload.update(payload_metadata)
        return payload
    return {"data": payload, **payload_metadata}


def accept_quote(quote_id: str, wallet: str) -> Dict[str, Any]:
    """Accept a quote produced by :func:`get_quote`."""

    response = binance_client.post(
        "/sapi/v1/convert/acceptQuote",
        {"quoteId": quote_id, "walletType": wallet.upper()},
    )
    return response.json()


def get_order_status(order_id: int | str) -> Dict[str, Any]:
    """Return status information for an accepted quote."""

    response = binance_client.get(
        "/sapi/v1/convert/orderStatus", {"orderId": order_id}
    )
    return response.json()


def get_trade_flow(start_ms: int, end_ms: int, limit: int = 100) -> Dict[str, Any]:
    """Return historical convert trades for the provided period."""

    response = binance_client.get(
        "/sapi/v1/convert/tradeFlow",
        {"startTime": start_ms, "endTime": end_ms, "limit": limit},
    )
    return response.json()
