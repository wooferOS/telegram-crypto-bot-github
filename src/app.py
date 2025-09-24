"""Auto-cycle orchestrator for Binance Convert flows."""

from __future__ import annotations

import argparse
import logging
from typing import Dict, Any

import sys
from pathlib import Path

import config_dev3 as config

from src.core import convert_api, scheduler
from src.core.utils import now_ms
from src import reporting
from src.strategy.selector import select_routes_for_phase


LOGGER = logging.getLogger(__name__)


def _valid_route(route: Dict[str, Any]) -> bool:
    fa = (route.get("from") or "").upper().strip()
    ta = (route.get("to") or "").upper().strip()
    amt = route.get("amount")
    try:
        amt = float(amt)
    except Exception:
        amt = 0.0
    return bool(fa and ta and amt > 0)


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
    collected = []  # ← акумуляція для звітів
    for route in select_routes_for_phase(region, "analyze"):
        if quote_budget and used >= quote_budget:
            LOGGER.warning("Quote budget %s reached", quote_budget)
            break
        try:
            quote = _quote_route(route)
            used += 1
            _log_quote("ANALYZE", quote)
            collected.append(
                quote
                if isinstance(quote, dict)
                else {"error": "non-dict response", **route}
            )
        except Exception as exc:  # pragma: no cover - network/API dependent
            LOGGER.error("Analyze quote failed for %s: %s", route, exc)
            collected.append({"error": str(exc), **route})
            continue

    # після збору пишемо звіти
    try:
        outdir = reporting.write_reports(collected)
        LOGGER.info("ANALYZE reports written to %s, rows=%s", outdir, len(collected))
    except Exception as exc:
        LOGGER.error("Analyze reporting failed: %s", exc)


def _trade(region: str, quote_budget: int, dry_run: bool) -> None:
    used = 0
    for route in select_routes_for_phase(region, "trade"):
        if quote_budget and used >= quote_budget:
            LOGGER.warning("Quote budget %s reached", quote_budget)
            break
        try:
            quote = _quote_route(route)
            used += 1
            _log_quote("TRADE", quote)

            quote_id = quote.get("quoteId")
            if not quote_id:
                LOGGER.warning("No quoteId for route: %s", route)
                # все одно зафіксуємо трейд у звіті як ok=True (dry-run)
                try:
                    reporting.write_reports(
                        [
                            {
                                "region": region,
                                "phase": "trade",
                                "from": route.get("from"),
                                "to": route.get("to"),
                                "wallet": route.get("wallet"),
                                "amount": route.get("amount"),
                                "ratio": quote.get("ratio") or quote.get("price"),
                                "toAmount": quote.get("toAmount")
                                or quote.get("toAmountExpected"),
                                "available": "",
                                "insufficient": False,
                                "ok": True,
                                "quoteId": "",
                                "error": "no-quote-id",
                            }
                        ]
                    )
                except Exception as _e:
                    LOGGER.error("Trade reporting failed: %s", _e)
                continue

            if dry_run:
                # тільки звіт про намір трейду (без accept)
                try:
                    reporting.write_reports(
                        [
                            {
                                "region": region,
                                "phase": "trade",
                                "from": route.get("from"),
                                "to": route.get("to"),
                                "wallet": route.get("wallet"),
                                "amount": route.get("amount"),
                                "ratio": quote.get("ratio") or quote.get("price"),
                                "toAmount": quote.get("toAmount")
                                or quote.get("toAmountExpected"),
                                "available": "",
                                "insufficient": False,
                                "ok": True,
                                "quoteId": quote_id,
                                "error": "",
                            }
                        ]
                    )
                except Exception as _e:
                    LOGGER.error("Trade reporting failed: %s", _e)
                continue

            # live режим: приймаємо котирування
            try:
                status = convert_api.accept_quote(quote_id)
            except Exception as exc:
                LOGGER.error("accept_quote failed for %s: %s", route, exc)
                try:
                    reporting.write_reports(
                        [
                            {
                                "region": region,
                                "phase": "order",
                                "from": route.get("from"),
                                "to": route.get("to"),
                                "wallet": route.get("wallet"),
                                "amount": route.get("amount"),
                                "ratio": quote.get("ratio") or quote.get("price"),
                                "toAmount": "",
                                "available": "",
                                "insufficient": False,
                                "ok": False,
                                "quoteId": quote_id,
                                "error": str(exc),
                            }
                        ]
                    )
                except Exception as _e:
                    LOGGER.error("Order reporting failed: %s", _e)
                continue

            # звіт про успішне замовлення
            try:
                reporting.write_reports(
                    [
                        {
                            "region": region,
                            "phase": "order",
                            "from": route.get("from"),
                            "to": route.get("to"),
                            "wallet": route.get("wallet"),
                            "amount": route.get("amount"),
                            "ratio": quote.get("ratio") or quote.get("price"),
                            "toAmount": status.get("toAmount"),
                            "available": "",
                            "insufficient": False,
                            "ok": True,
                            "quoteId": quote_id,
                            "error": "",
                        }
                    ]
                )
            except Exception as _e:
                LOGGER.error("Order reporting failed: %s", _e)

        except Exception as exc:  # pragma: no cover - network/API dependent
            LOGGER.error("Trade quote failed for %s: %s", route, exc)
            try:
                reporting.write_reports(
                    [
                        {
                            "region": region,
                            "phase": "trade",
                            "from": route.get("from"),
                            "to": route.get("to"),
                            "wallet": route.get("wallet"),
                            "amount": route.get("amount"),
                            "ratio": "",
                            "toAmount": "",
                            "available": "",
                            "insufficient": False,
                            "ok": False,
                            "quoteId": "",
                            "error": str(exc),
                        }
                    ]
                )
            except Exception as _e:
                LOGGER.error("Trade reporting failed: %s", _e)


def run(region: str, phase: str, dry_run: bool) -> None:
    _setup_logging()
    region = region.lower()
    phase = phase.lower()

    budget = int(getattr(config, "QUOTE_BUDGET_PER_RUN", 0))
    lock_name = f"{region}_{phase}"

    with scheduler.single_instance_lock(lock_name):
        if not scheduler.in_window(region, phase):
            import os as _os

            if _os.getenv("CONVERT_FORCE", "0") == "1":
                LOGGER.warning("FORCE: bypassing configured window via CONVERT_FORCE=1")
            else:
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


def _resolve_outdir(outdir):
    import os
    from pathlib import Path
    from datetime import datetime, timezone

    if outdir:
        return outdir
    root = os.environ.get("CONVERT_LOG_ROOT", "/srv/dev3/logs/convert")
    return str(Path(root) / datetime.now(timezone.utc).strftime("%Y-%m-%d"))
