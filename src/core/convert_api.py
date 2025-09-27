"""High level helpers around Binance Convert endpoints."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

import config_dev3 as config

from . import binance_client
from .utils import (
    DECIMAL_ZERO,
    decimal_from_any,
    ensure_amount_and_limits,
    now_ms,
    rand_jitter,
)

LOGGER = logging.getLogger(__name__)


def _log_getquote_response(resp):
    try:
        if "/sapi/v1/convert/getQuote" in getattr(resp, "url", "") and int(getattr(resp, "status_code", 0)) >= 400:
            LOGGER.error(
                "getQuote failed: url=%s status=%s body=%s",
                getattr(resp, "url", ""),
                getattr(resp, "status_code", None),
                getattr(resp, "text", ""),
            )
    except Exception:
        pass


HUB_ASSETS: Tuple[str, ...] = ("BTC", "ETH", "BNB", "USDT")

_JITTER_RANGE_SEC: Tuple[float, float] = tuple(
    x / 1000.0 for x in getattr(config, "CONVERT_JITTER_MS", (500, 1200))
) or (0.5, 1.2)
_QUOTE_TTL_SAFETY_MS = getattr(config, "QUOTE_TTL_SAFETY_MS", 1200)
_QUOTE_RETRY_MAX = getattr(config, "QUOTE_RETRY_MAX", 2)

# Deduplication cache within process execution
_executed_keys: set[str] = set()


@dataclass(frozen=True)
class ConvertStep:
    """Single hop in convert route."""

    from_asset: str
    to_asset: str


@dataclass
class ConvertRoute:
    """Concrete convert route possibly containing hub assets."""

    steps: Tuple[ConvertStep, ...]

    @property
    def is_direct(self) -> bool:
        return len(self.steps) == 1

    @property
    def description(self) -> str:
        if self.is_direct:
            step = self.steps[0]
            return f"direct:{step.from_asset}->{step.to_asset}"
        hubs = ",".join(step.to_asset for step in self.steps[:-1])
        return f"hub:{hubs}"


@dataclass
class ConvertLimits:
    """Convert limits (min/max) in *from* asset units."""

    minimum: Decimal
    maximum: Decimal


@dataclass
class ConvertQuote:
    """Structured representation of Convert quote response."""

    quote_id: str
    from_asset: str
    to_asset: str
    from_amount: Decimal
    to_amount: Decimal
    price: Decimal
    expire_time_ms: int
    raw: Dict[str, Any]

    def expired(self, safety_ms: int = _QUOTE_TTL_SAFETY_MS) -> bool:
        if not self.expire_time_ms:
            return False
        return now_ms() >= max(0, self.expire_time_ms - int(abs(safety_ms)))


def _sleep_with_jitter() -> None:
    jitter = rand_jitter(_JITTER_RANGE_SEC)
    if jitter > 0:
        time.sleep(jitter)


def _normalise_asset(value: str) -> str:
    return (value or "").upper().strip()


def _safe_exchange_info(from_asset: str, to_asset: str) -> Optional[Dict[str, Any]]:
    try:
        return binance_client.get_convert_exchange_info(from_asset, to_asset)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (400, 404):
            return None
        raise
    except requests.RequestException:
        raise


def _extract_limits(info: Optional[Dict[str, Any]]) -> ConvertLimits:
    if not info:
        return ConvertLimits(DECIMAL_ZERO, DECIMAL_ZERO)
    payload: Any = info
    if isinstance(info, dict) and "data" in info:
        payload = info.get("data")
    if not isinstance(payload, dict):
        payload = {}
    minimum = decimal_from_any(payload.get("fromAssetMinAmount"))
    maximum = decimal_from_any(payload.get("fromAssetMaxAmount"))
    return ConvertLimits(minimum, maximum)


@lru_cache(maxsize=8192)
def _route_steps(from_asset: str, to_asset: str) -> Optional[ConvertRoute]:
    if from_asset == to_asset:
        return ConvertRoute((ConvertStep(from_asset, to_asset),))
    info = _safe_exchange_info(from_asset, to_asset)
    if info:
        return ConvertRoute((ConvertStep(from_asset, to_asset),))
    for hub in HUB_ASSETS:
        if hub in (from_asset, to_asset):
            continue
        first = _safe_exchange_info(from_asset, hub)
        if not first:
            continue
        second = _safe_exchange_info(hub, to_asset)
        if not second:
            continue
        return ConvertRoute((ConvertStep(from_asset, hub), ConvertStep(hub, to_asset)))
    return None


def route_exists(from_asset: str, to_asset: str) -> Optional[ConvertRoute]:
    """Return :class:`ConvertRoute` if conversion possible."""

    from_asset = _normalise_asset(from_asset)
    to_asset = _normalise_asset(to_asset)
    if not from_asset or not to_asset:
        return None
    return _route_steps(from_asset, to_asset)


def limits_for_pair(from_asset: str, to_asset: str) -> ConvertLimits:
    return _extract_limits(_safe_exchange_info(from_asset, to_asset))


def get_asset_precision(asset: str) -> Dict[str, Any]:
    return binance_client.get_convert_asset_info(asset)


def _quote_once(
    from_asset: str,
    to_asset: str,
    amount: Decimal,
    wallet: str = "SPOT",
    allow_insufficient: bool = False,
) -> Optional[ConvertQuote]:
    params = {
        "fromAsset": from_asset,
        "toAsset": to_asset,
        "fromAmount": str(amount),
        "walletType": (wallet or "SPOT").upper(),
    }
    _sleep_with_jitter()
    payload = binance_client.post("/sapi/v1/convert/getQuote", params, signed=True)
    _log_getquote_response(payload)
    if not isinstance(payload, dict):
        return None
    if payload.get("insufficient") and not allow_insufficient:
        return None
    expire_raw = payload.get("expireTime") or payload.get("validTimestamp")
    expire_ms = int(expire_raw) if expire_raw else 0
    price = decimal_from_any(payload.get("ratio") or payload.get("price"))
    to_amount = decimal_from_any(payload.get("toAmount") or payload.get("toAmountExpected"))
    quote = ConvertQuote(
        quote_id=str(payload.get("quoteId", "")),
        from_asset=from_asset,
        to_asset=to_asset,
        from_amount=decimal_from_any(amount),
        to_amount=to_amount,
        price=price,
        expire_time_ms=expire_ms,
        raw=payload,
    )
    return quote


def get_quote(
    from_asset: str,
    to_asset: str,
    amount: Decimal,
    wallet: str = "SPOT",
    retry: int | None = None,
) -> Optional[ConvertQuote]:
    """Fetch Convert quote with TTL-awareness and retries."""

    attempts = retry if retry is not None else max(1, _QUOTE_RETRY_MAX)
    for attempt in range(1, attempts + 1):
        quote = _quote_once(from_asset, to_asset, amount, wallet)
        if quote:
            return quote
        if attempt < attempts:
            _sleep_with_jitter()
    return None


def accept_quote(quote: ConvertQuote | str) -> Dict[str, Any]:
    """
    Accept a quote by quoteId; supports str or object with quote_id.
    """
    quote_id = quote if isinstance(quote, str) else getattr(quote, "quote_id", None)
    assert quote_id, "acceptQuote(): missing quoteId"
    try:
        return binance_client.post("/sapi/v1/convert/acceptQuote", {"quoteId": quote_id}, signed=True)
    except Exception as e:
        resp = getattr(e, "response", None)
        try:
            sc = int(getattr(resp, "status_code", 0))
        except Exception:
            sc = 0
        if sc >= 400:
            import logging

            logging.getLogger(__name__).error(
                "acceptQuote failed: status=%s body=%s", getattr(resp, "status_code", None), getattr(resp, "text", "")
            )
        raise


def order_status(order_id: str) -> Dict[str, Any]:
    return binance_client.get("/sapi/v1/convert/orderStatus", {"orderId": order_id}, signed=True)


def execute_conversion(
    from_asset: str,
    to_asset: str,
    amount: Decimal,
    wallet: str = "SPOT",
    retry: int | None = None,
) -> Dict[str, Any]:
    """Execute direct conversion (single hop)."""

    info = _safe_exchange_info(from_asset, to_asset)
    if info:
        ensure_amount_and_limits(info, amount)
    quote = get_quote(from_asset, to_asset, amount, wallet, retry=retry)
    if not quote:
        raise RuntimeError(f"quote failed for {from_asset}->{to_asset}")
    if quote.expired():
        LOGGER.warning("Quote %s expired immediately, requesting a new one", quote.quote_id)
        quote = get_quote(from_asset, to_asset, amount, wallet, retry=retry)
        if not quote:
            raise RuntimeError("quote failed after retry")
    result = accept_quote(quote)
    result.setdefault("quote", quote.raw)
    return result


def execute_route(
    route: ConvertRoute,
    amount: Decimal,
    wallet: str = "SPOT",
    retry: int | None = None,
) -> List[Dict[str, Any]]:
    """Execute route (direct or hub) returning list of order payloads."""

    executed: List[Dict[str, Any]] = []
    current_amount = amount
    for step in route.steps:
        response = execute_conversion(step.from_asset, step.to_asset, current_amount, wallet, retry)
        executed.append(response)
        quote = response.get("quote", {})
        current_amount = decimal_from_any(quote.get("toAmount") or quote.get("toAmountExpected"))
        wallet = (wallet or "SPOT").upper()
    return executed


def execute_unique(
    route: ConvertRoute, amount: Decimal, wallet: str, tolerance: float = 0.01
) -> Optional[List[Dict[str, Any]]]:
    key = json.dumps(
        {
            "route": [f"{step.from_asset}->{step.to_asset}" for step in route.steps],
            "amount": float(amount),
            "wallet": wallet,
        },
        sort_keys=True,
    )
    for existing in list(_executed_keys):
        try:
            payload = json.loads(existing)
        except Exception:
            continue
        if payload.get("wallet") != wallet:
            continue
        if payload.get("route") != [f"{step.from_asset}->{step.to_asset}" for step in route.steps]:
            continue
        prev_amount = float(payload.get("amount", 0.0))
        if prev_amount <= 0:
            continue
        diff = abs(prev_amount - float(amount)) / prev_amount
        if diff <= tolerance:
            LOGGER.info("Skip duplicate convert %s (within %.2f%%)", route.description, tolerance * 100)
            return None
    _executed_keys.add(key)
    return execute_route(route, amount, wallet)


def reset_dedup_cache() -> None:
    _executed_keys.clear()


def preferred_route(from_assets: Iterable[str], target: str) -> Optional[ConvertRoute]:
    target = _normalise_asset(target)
    for asset in {_normalise_asset(a) for a in from_assets}:
        if not asset:
            continue
        route = route_exists(asset, target)
        if route:
            return route
    return None


def get_trade_flow(start_time: int, end_time: int, limit: int = 100) -> Dict[str, Any]:
    params = {"startTime": int(start_time), "endTime": int(end_time), "limit": int(limit)}
    return binance_client.get("/sapi/v1/convert/tradeFlow", params, signed=True)
