"""Auto-cycle orchestrator for Binance Convert flows."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import config_dev3 as config

from src.core import convert_api, scheduler
from src.core.utils import now_ms
from src.strategy.selector import select_routes_for_phase


LOGGER = logging.getLogger(__name__)


def _setup_logging() -> None:
    if logging.getLogger().handlers:
        return
    log_path = Path(getattr(config, "LOG_PATH", "convert.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _effective_dry_run(cli_value: int | None) -> bool:
    if cli_value is None:
        return bool(getattr(config, "DRY_RUN", 0))
    return bool(cli_value)


def _log_quote(prefix: str, quote: dict) -> None:
    ratio = quote.get("ratio") or quote.get("price")
    to_amount = quote.get("toAmount") or quote.get("toAmountExpected")
    LOGGER.info(
        "%s %s→%s wallet=%s amount=%s ratio=%s toAmount=%s",
        prefix,
        quote.get("fromAsset"),
        quote.get("toAsset"),
        quote.get("wallet"),
        quote.get("requestedAmount"),
        ratio,
        to_amount,
    )


def _quote_route(route: dict) -> dict:
    return convert_api.get_quote(
        route["from"],
        route["to"],
        route.get("amount", "ALL"),
        route.get("wallet", "SPOT"),
    )


def _analyze(region: str, quote_budget: int) -> None:
    used = 0
    for route in select_routes_for_phase(region, "analyze"):
        if quote_budget and used >= quote_budget:
            LOGGER.warning("Quote budget %s reached", quote_budget)
            break
        try:
            quote = _quote_route(route)
        except Exception as exc:  # pragma: no cover - network/API dependent
            LOGGER.error("Analyze quote failed for %s: %s", route, exc)
            continue
        used += 1
        _log_quote("ANALYZE", quote)


def _trade(region: str, quote_budget: int, dry_run: bool) -> None:
    used = 0
    for route in select_routes_for_phase(region, "trade"):
        if quote_budget and used >= quote_budget:
            LOGGER.warning("Quote budget %s reached", quote_budget)
            break
        try:
            quote = _quote_route(route)
        except Exception as exc:  # pragma: no cover - network/API dependent
            LOGGER.error("Trade quote failed for %s: %s", route, exc)
            continue
        used += 1
        _log_quote("QUOTE", quote)
        if quote.get("insufficient"):
            LOGGER.warning(
                "Insufficient balance for %s→%s wallet=%s available=%s requested=%s",
                quote.get("fromAsset"),
                quote.get("toAsset"),
                quote.get("wallet"),
                quote.get("available"),
                quote.get("requestedAmount"),
            )
            continue
        quote_id = quote.get("quoteId")
        if not quote_id:
            LOGGER.warning("Quote missing quoteId for %s", route)
            continue
        if dry_run:
            LOGGER.info("Dry run active — skipping acceptQuote for %s", quote_id)
            continue
        try:
            accept = convert_api.accept_quote(str(quote_id), quote.get("wallet", "SPOT"))
        except Exception as exc:  # pragma: no cover - network/API dependent
            LOGGER.error("acceptQuote failed for %s: %s", quote_id, exc)
            continue
        order_id = accept.get("orderId") if isinstance(accept, dict) else None
        LOGGER.info("ACCEPT quote=%s order=%s", quote_id, order_id)
        if not order_id:
            continue
        try:
            status = convert_api.get_order_status(order_id)
        except Exception as exc:  # pragma: no cover - network/API dependent
            LOGGER.error("orderStatus failed for %s: %s", order_id, exc)
            continue
        LOGGER.info(
            "ORDER %s status=%s toAmount=%s", order_id, status.get("status"), status.get("toAmount")
        )


def run(region: str, phase: str, dry_run: bool) -> None:
    _setup_logging()
    region = region.lower()
    phase = phase.lower()

    budget = int(getattr(config, "QUOTE_BUDGET_PER_RUN", 0))
    lock_name = f"{region}_{phase}"

    with scheduler.single_instance_lock(lock_name):
        if not scheduler.in_window(region, phase):
            LOGGER.info("Outside configured window for %s/%s", region, phase)
            return

        scheduler.sleep_with_jitter_before_phase(region, phase)

        LOGGER.info(
            "Starting %s/%s dry_run=%s timestamp=%s",
            region,
            phase,
            dry_run,
            now_ms(),
        )
        if phase == "analyze":
            _analyze(region, budget)
        elif phase == "trade":
            _trade(region, budget, dry_run)
        else:  # pragma: no cover - guarded by argparse
            raise ValueError(f"Unknown phase {phase}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True, choices=["asia", "us"])
    parser.add_argument("--phase", required=True, choices=["analyze", "trade"])
    parser.add_argument("--dry-run", type=int, choices=[0, 1], default=None)
    args = parser.parse_args(argv)

    dry_run = _effective_dry_run(args.dry_run)
    try:
        run(args.region, args.phase, dry_run)
    except Exception as exc:  # pragma: no cover - top-level guard
        _setup_logging()
        LOGGER.exception("Run failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
