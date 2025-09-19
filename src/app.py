"""High level orchestration for the Binance Convert auto-cycle."""
from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Tuple

from config_dev3 import (
    DRY_RUN_DEFAULT,
    ORDER_POLL_SEC,
    ORDER_POLL_TIMEOUT_SEC,
    QUOTE_BUDGET_PER_RUN,
)
from src.core import balance, convert_api, scheduler, utils
from src.strategy import selector

LOGGER = logging.getLogger(__name__)
ZERO = Decimal("0")


def run(region: str, phase: str, *, dry_run: bool | None = None) -> None:
    region = region.lower()
    phase = phase.lower()
    if dry_run is None:
        dry_run = DRY_RUN_DEFAULT

    LOGGER.info("Starting %s phase for %s (dry_run=%s)", phase, region, dry_run)

    with scheduler.acquire_lock(region):
        if phase == "analyze":
            if not scheduler.is_analyze_window(region):
                LOGGER.info("Outside analyze window for %s", region)
                return
        elif phase == "trade":
            if not scheduler.is_trade_window(region):
                LOGGER.info("Outside trade window for %s", region)
                return
        else:  # pragma: no cover - defensive
            raise ValueError(f"Unknown phase: {phase}")

        delay = scheduler.jitter_start()
        if delay:
            LOGGER.info("Applied jitter delay %.2fs", delay)

        plans = selector.build_plan(region)
        quotes_used = 0
        for candidate in plans:
            if quotes_used >= QUOTE_BUDGET_PER_RUN:
                LOGGER.warning(
                    "Quote budget exhausted (%s per run)", QUOTE_BUDGET_PER_RUN
                )
                break
            consumed, _ = _process_candidate(
                candidate, allow_trade=phase == "trade", dry_run=dry_run
            )
            if consumed:
                quotes_used += 1

        LOGGER.info(
            "Finished %s phase for %s; quotes_used=%s", phase, region, quotes_used
        )


def quote_once(from_asset: str, to_asset: str, amount: str, wallet: str) -> Dict[str, Any]:
    candidate = {
        "from": from_asset,
        "to": to_asset,
        "wallet": wallet,
        "amount": amount,
        "priority": 0,
    }
    _, result = _process_candidate(candidate, allow_trade=False, dry_run=True)
    return result


def convert_once(
    from_asset: str, to_asset: str, amount: str, wallet: str, *, dry_run: bool
) -> Dict[str, Any]:
    candidate = {
        "from": from_asset,
        "to": to_asset,
        "wallet": wallet,
        "amount": amount,
        "priority": 0,
    }
    _, result = _process_candidate(
        candidate, allow_trade=not dry_run, dry_run=dry_run
    )
    return result


def _process_candidate(
    candidate: Dict[str, Any], *, allow_trade: bool, dry_run: bool
) -> Tuple[bool, Dict[str, Any]]:
    from_asset = candidate["from"].upper()
    to_asset = candidate["to"].upper()
    wallet = candidate.get("wallet", "SPOT").upper()
    amount_spec = candidate.get("amount", "ALL")
    label = f"{from_asset}->{to_asset} ({wallet})"

    try:
        info = convert_api.exchange_info(from_asset, to_asset)
    except Exception as exc:
        LOGGER.error("exchangeInfo failed for %s: %s", label, exc)
        return False, {"error": str(exc), "stage": "exchangeInfo"}

    min_amount, max_amount = extract_limits(info)
    try:
        amount_dec, free_balance, amount_str = _resolve_amount(
            from_asset, wallet, amount_spec, min_amount, max_amount
        )
    except Exception as exc:
        LOGGER.error("Failed to resolve amount for %s: %s", label, exc)
        return False, {"error": str(exc), "stage": "amount"}

    if amount_dec is None:
        reason = amount_str  # type: ignore[assignment]
        LOGGER.info("Skipping %s: %s", label, reason)
        return False, {"skipped": reason}

    LOGGER.info(
        "Preparing quote %s amount=%s free=%s min=%s max=%s",
        label,
        amount_str,
        free_balance,
        min_amount,
        max_amount if max_amount > ZERO else "unlimited",
    )

    try:
        quote = convert_api.get_quote(from_asset, to_asset, amount_str, wallet)
    except Exception as exc:
        LOGGER.error("getQuote failed for %s: %s", label, exc)
        return False, {"error": str(exc), "stage": "getQuote"}

    consumed = True
    result: Dict[str, Any] = {
        "candidate": candidate,
        "amount": amount_str,
        "free_balance": str(free_balance),
        "quote": quote,
        "min_amount": str(min_amount),
        "max_amount": str(max_amount),
        "dry_run": dry_run,
    }

    quote_id = quote.get("quoteId") if isinstance(quote, dict) else None
    if not quote_id:
        LOGGER.warning("Quote without quoteId for %s: %s", label, quote)
        return consumed, result

    if not allow_trade or dry_run:
        LOGGER.info("Dry run quote for %s: %s", label, quote_id)
        return consumed, result

    try:
        accepted = convert_api.accept_quote(str(quote_id), wallet)
    except Exception as exc:
        LOGGER.error("acceptQuote failed for %s: %s", label, exc)
        result["accept_error"] = str(exc)
        return consumed, result

    order_id = accepted.get("orderId") if isinstance(accepted, dict) else None
    result["accepted"] = accepted

    if not order_id:
        LOGGER.warning("acceptQuote did not return orderId for %s", label)
        return consumed, result

    status = _poll_order_status(order_id)
    result["order_status"] = status
    return consumed, result


def _poll_order_status(order_id: Any) -> Dict[str, Any]:
    deadline = time.time() + ORDER_POLL_TIMEOUT_SEC
    last_status: Dict[str, Any] = {"status": "UNKNOWN"}
    while time.time() < deadline:
        try:
            status = convert_api.order_status(order_id)
        except Exception as exc:
            LOGGER.warning("orderStatus failed for %s: %s", order_id, exc)
            time.sleep(ORDER_POLL_SEC)
            continue

        last_status = status if isinstance(status, dict) else {"raw": status}
        state = last_status.get("status")
        LOGGER.info("orderStatus %s -> %s", order_id, state)
        if state in {"SUCCESS", "FAIL"}:
            return last_status
        time.sleep(ORDER_POLL_SEC)

    LOGGER.warning("Timeout waiting for order %s status", order_id)
    last_status.setdefault("status", "TIMEOUT")
    return last_status


def extract_limits(info: Dict[str, Any]) -> Tuple[Decimal, Decimal]:
    payload = info if isinstance(info, dict) else {}
    if isinstance(info, dict) and "data" in info and isinstance(info["data"], dict):
        payload = info["data"]
    min_amount = _to_decimal(payload.get("fromAssetMinAmount")) if isinstance(payload, dict) else ZERO
    max_amount = _to_decimal(payload.get("fromAssetMaxAmount")) if isinstance(payload, dict) else ZERO
    return min_amount, max_amount


def _resolve_amount(
    from_asset: str,
    wallet: str,
    amount_spec: Any,
    min_amount: Decimal,
    max_amount: Decimal,
) -> Tuple[Decimal | None, Decimal, str]:
    available = balance.read_free(from_asset, wallet)
    if isinstance(amount_spec, str) and amount_spec.upper() == "ALL":
        target = available
    else:
        try:
            target = Decimal(str(amount_spec))
        except (InvalidOperation, ValueError):
            return None, available, "invalid amount"

    amount_str = utils.floor_str_8(target)
    if not amount_str:
        return None, available, "zero amount"
    amount_dec = Decimal(amount_str)

    if amount_dec <= ZERO:
        return None, available, "zero amount"

    if max_amount > ZERO and amount_dec > max_amount:
        amount_dec = Decimal(utils.floor_str_8(max_amount))
        amount_str = utils.floor_str_8(amount_dec)

    if amount_dec < min_amount:
        return None, available, f"amount {amount_dec} below minimum {min_amount}"

    if amount_dec > available:
        return None, available, f"insufficient balance {available}"

    return amount_dec, available, amount_str


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO
