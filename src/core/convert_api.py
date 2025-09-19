"""Lightweight wrappers around Binance Convert endpoints."""
from __future__ import annotations

import random
import time
from typing import Any, Dict

from src.core import binance_client


def exchange_info(from_asset: str, to_asset: str) -> Dict[str, Any]:
    response = binance_client.get(
        "/sapi/v1/convert/exchangeInfo",
        {"fromAsset": from_asset, "toAsset": to_asset},
    )
    return response.json()


def get_quote(from_asset: str, to_asset: str, from_amount: str, wallet: str) -> Dict[str, Any]:
    # small jitter before hitting quote endpoint repeatedly
    time.sleep(random.uniform(0.05, 0.15))
    response = binance_client.post(
        "/sapi/v1/convert/getQuote",
        {
            "fromAsset": from_asset,
            "toAsset": to_asset,
            "fromAmount": from_amount,
            "walletType": wallet,
        },
    )
    return response.json()


def accept_quote(quote_id: str, wallet: str) -> Dict[str, Any]:
    response = binance_client.post(
        "/sapi/v1/convert/acceptQuote",
        {"quoteId": quote_id, "walletType": wallet},
    )
    return response.json()


def order_status(order_id: int | str) -> Dict[str, Any]:
    response = binance_client.get(
        "/sapi/v1/convert/orderStatus", {"orderId": order_id}
    )
    return response.json()


def trade_flow(start_ms: int, end_ms: int, limit: int = 100) -> Dict[str, Any]:
    response = binance_client.get(
        "/sapi/v1/convert/tradeFlow",
        {"startTime": start_ms, "endTime": end_ms, "limit": limit},
    )
    return response.json()
