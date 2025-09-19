"""High level orchestration for the Binance Convert auto-cycle."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import config_dev3 as config

from src.core import convert_api, scheduler, utils
from src.core.convert_api import ConvertError
from src.strategy import selector

LOGGER = logging.getLogger(__name__)

DEFAULT_DRY_RUN = bool(getattr(config, "DRY_RUN", False))
QUOTE_BUDGET_PER_RUN = int(getattr(config, "QUOTE_BUDGET_PER_RUN", 0))
ORDER_POLL_SEC = int(getattr(config, "ORDER_POLL_SEC", 2))
ORDER_POLL_TIMEOUT_SEC = int(getattr(config, "ORDER_POLL_TIMEOUT_SEC", 60))
JITTER_SEC = int(getattr(config, "JITTER_SEC", 0))

PLANS: Dict[str, List[Dict[str, Any]]] = {}


@dataclass
class QuoteBudget:
    limit: int
    used: int = 0

    def allow(self) -> bool:
        return self.limit <= 0 or self.used < self.limit

    def consume(self) -> None:
        if self.limit > 0:
            self.used += 1


def run(region: str, phase: str, *, dry_run: Optional[bool] = None) -> None:
    """Execute the requested ``phase`` for ``region`` respecting all guards."""

    region = region.lower()
    phase = phase.lower()
    now = datetime.now(timezone.utc)
    is_dry_run = DEFAULT_DRY_RUN if dry_run is None else dry_run

    LOGGER.info("Starting %s phase for %s (dry_run=%s)", phase, region, is_dry_run)

    with scheduler.acquire_lock(region):
        if phase == "analyze":
            if not scheduler.is_in_analyze_window(region, now):
                LOGGER.info("Outside analyze window for %s", region)
                return
            _apply_phase_jitter()
            plan = _analyze(region)
            PLANS[region] = plan
            LOGGER.info("Analyze complete for %s; %s step(s) stored", region, len(plan))
            return

        if phase == "trade":
            if not scheduler.is_in_trade_window(region, now):
                LOGGER.info("Outside trade window for %s", region)
                return
            _apply_phase_jitter()
            steps = [entry["step"] for entry in PLANS.get(region, [])]
            if not steps:
                LOGGER.warning("No cached plan for %s; rebuilding from selector", region)
                steps = selector.build_plan(region)
            results = _trade(region, steps, dry_run=is_dry_run)
            if not is_dry_run:
                PLANS.pop(region, None)
            LOGGER.info(
                "Trade complete for %s; executed=%s", region, len(results)
            )
            return

        raise ValueError(f"Unknown phase: {phase}")


def quote_once(from_asset: str, to_asset: str, amount: str, wallet: str) -> Dict[str, Any]:
    """Return a preview quote for manual CLI usage."""

    return _quote_step({"from": from_asset, "to": to_asset, "wallet": wallet, "amount": amount})


def convert_once(
    from_asset: str,
    to_asset: str,
    amount: str,
    wallet: str,
    *,
    dry_run: bool,
) -> Dict[str, Any]:
    """Execute a single conversion respecting dry-run mode."""

    step = {"from": from_asset, "to": to_asset, "wallet": wallet, "amount": amount}
    result = _quote_step(step)
    if result.get("insufficient"):
        result["status"] = "SKIPPED"
        result["reason"] = "insufficient balance"
        return result
    if dry_run:
        result["status"] = "DRY_RUN"
        return result

    accept = convert_api.accept_quote(str(result.get("quoteId")), wallet)
    result["accept"] = accept
    order_id = accept.get("orderId") if isinstance(accept, dict) else None
    if order_id:
        result["orderStatus"] = _poll_order_status(order_id)
    else:
        result["orderStatus"] = {"status": "UNKNOWN"}
    result["status"] = "DONE"
    return result


def _apply_phase_jitter() -> None:
    if JITTER_SEC <= 0:
        return
    delay = utils.sleep_jitter(0, JITTER_SEC * 1000)
    if delay:
        LOGGER.info("Applied start jitter %.2fs", delay)


def _analyze(region: str) -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    budget = QuoteBudget(QUOTE_BUDGET_PER_RUN)

    for step in selector.build_plan(region):
        if not budget.allow():
            LOGGER.warning("Quote budget exhausted (%s)", QUOTE_BUDGET_PER_RUN)
            break
        try:
            quote = _quote_step(step)
            budget.consume()
            plan.append({"step": step, "quote": quote, "timestamp": utils.now_ms()})
            LOGGER.info(
                "Analyze %s -> %s (%s) amount=%s price=%s",
                step["from"],
                step["to"],
                step["wallet"],
                quote.get("amount"),
                quote.get("price", quote.get("ratio")),
            )
        except ConvertError as exc:
            LOGGER.warning("Skipping %s during analyze: %s", step, exc)
        except Exception as exc:  # pragma: no cover - network dependent
            LOGGER.error("Quote failed during analyze %s: %s", step, exc)
    return plan


def _trade(region: str, steps: List[Dict[str, Any]], *, dry_run: bool) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    budget = QuoteBudget(QUOTE_BUDGET_PER_RUN)

    for step in steps:
        if not budget.allow():
            LOGGER.warning("Quote budget exhausted (%s)", QUOTE_BUDGET_PER_RUN)
            break
        try:
            quote = _quote_step(step)
            budget.consume()
        except ConvertError as exc:
            LOGGER.error("Quote validation failed for %s: %s", step, exc)
            continue
        except Exception as exc:  # pragma: no cover - network dependent
            LOGGER.error("Quote failed for %s: %s", step, exc)
            continue

        if quote.get("insufficient"):
            LOGGER.warning(
                "Insufficient balance for %s -> %s (%s); available=%s amount=%s",
                step["from"],
                step["to"],
                step["wallet"],
                quote.get("available"),
                quote.get("amount"),
            )
            results.append({"step": step, "quote": quote, "status": "SKIPPED"})
            continue

        if dry_run:
            LOGGER.info(
                "Dry trade %s -> %s (%s) amount=%s price=%s",
                step["from"],
                step["to"],
                step["wallet"],
                quote.get("amount"),
                quote.get("price", quote.get("ratio")),
            )
            results.append({"step": step, "quote": quote, "status": "DRY_RUN"})
            continue

        order_result = _execute_trade(step, quote)
        results.append(order_result)
        utils.sleep_jitter(200, 600)

    return results


def _quote_step(step: Dict[str, Any]) -> Dict[str, Any]:
    quote = convert_api.get_quote(
        step["from"],
        step["to"],
        step.get("amount", "ALL"),
        step.get("wallet", "SPOT"),
    )
    LOGGER.debug("Quote result: %s", quote)
    return quote


def _execute_trade(step: Dict[str, Any], quote: Dict[str, Any]) -> Dict[str, Any]:
    wallet = step.get("wallet", "SPOT")
    quote_id = quote.get("quoteId")
    if not quote_id:
        LOGGER.error("Quote missing quoteId for %s", step)
        return {"step": step, "quote": quote, "status": "ERROR", "reason": "missing quoteId"}

    LOGGER.info(
        "Accepting quote %s for %s -> %s amount=%s", quote_id, step["from"], step["to"], quote.get("amount")
    )
    accept = convert_api.accept_quote(str(quote_id), wallet)
    order_id = accept.get("orderId") if isinstance(accept, dict) else None
    status = {"status": "PENDING"}
    if order_id:
        status = _poll_order_status(order_id)
    LOGGER.info(
        "Trade %s -> %s (%s) order=%s status=%s", step["from"], step["to"], wallet, order_id, status.get("status")
    )
    return {"step": step, "quote": quote, "accept": accept, "orderStatus": status, "status": status.get("status")}


def _poll_order_status(order_id: Any) -> Dict[str, Any]:
    deadline = time.time() + ORDER_POLL_TIMEOUT_SEC
    last_status: Dict[str, Any] = {"status": "UNKNOWN"}
    while time.time() < deadline:
        try:
            status = convert_api.get_order_status(order_id)
        except Exception as exc:  # pragma: no cover - network dependent
            LOGGER.warning("orderStatus failed for %s: %s", order_id, exc)
            time.sleep(ORDER_POLL_SEC)
            continue
        last_status = status if isinstance(status, dict) else {"status": "UNKNOWN", "raw": status}
        state = last_status.get("status")
        LOGGER.info("orderStatus %s -> %s", order_id, state)
        if state in {"SUCCESS", "FAIL"}:
            return last_status
        time.sleep(ORDER_POLL_SEC)
    last_status.setdefault("status", "TIMEOUT")
    LOGGER.warning("Timeout waiting for order %s status", order_id)
    return last_status
