"""Command line interface for Binance Convert automation."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from config_dev3 import DRY_RUN_DEFAULT
from src import app
from src.core import balance, convert_api, utils

LOGGER = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_info(args: argparse.Namespace) -> None:
    info = convert_api.exchange_info(args.from_asset, args.to_asset)
    min_amount, max_amount = app.extract_limits(info)

    print(json.dumps({"exchangeInfo": info}, indent=2, ensure_ascii=False))
    for wallet in ("SPOT", "FUNDING"):
        from_free = balance.read_free(args.from_asset, wallet)
        to_free = balance.read_free(args.to_asset, wallet)
        print(
            f"{wallet}: {args.from_asset}={from_free} {args.to_asset}={to_free}"
        )
    print(f"minAmount={min_amount} maxAmount={max_amount}")


def cmd_quote(args: argparse.Namespace) -> None:
    result = app.quote_once(
        args.from_asset,
        args.to_asset,
        args.amount,
        args.wallet,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_now(args: argparse.Namespace) -> None:
    result = app.convert_once(
        args.from_asset,
        args.to_asset,
        args.amount,
        args.wallet,
        dry_run=args.dry,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_status(args: argparse.Namespace) -> None:
    status = convert_api.order_status(args.order_id)
    print(json.dumps(status, indent=2, ensure_ascii=False))


def cmd_trades(args: argparse.Namespace) -> None:
    end_ms = utils.now_ms()
    start_ms = end_ms - int(args.hours * 3600 * 1000)
    trades = convert_api.trade_flow(start_ms, end_ms)
    if args.detailed:
        print(json.dumps(trades, indent=2, ensure_ascii=False))
        return
    items = trades.get("list") if isinstance(trades, dict) else None
    count = len(items) if isinstance(items, list) else 0
    print(f"Trades in last {args.hours}h: {count}")


def cmd_run(args: argparse.Namespace) -> None:
    dry_run = DRY_RUN_DEFAULT if args.dry is None else args.dry
    app.run(args.region, args.phase, dry_run=dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_info = subparsers.add_parser("info", help="Show pair limits and balances")
    p_info.add_argument("from_asset")
    p_info.add_argument("to_asset")
    p_info.set_defaults(func=cmd_info)

    p_quote = subparsers.add_parser("quote", help="Dry quote a conversion")
    p_quote.add_argument("from_asset")
    p_quote.add_argument("to_asset")
    p_quote.add_argument("amount")
    p_quote.add_argument("--wallet", default="SPOT", choices=["SPOT", "FUNDING"])
    p_quote.set_defaults(func=cmd_quote)

    p_now = subparsers.add_parser("now", help="Execute a conversion immediately")
    p_now.add_argument("from_asset")
    p_now.add_argument("to_asset")
    p_now.add_argument("amount")
    p_now.add_argument("--wallet", default="SPOT", choices=["SPOT", "FUNDING"])
    p_now.add_argument("--dry", action="store_true", help="Dry run without acceptQuote")
    p_now.set_defaults(func=cmd_now)

    p_status = subparsers.add_parser("status", help="Fetch order status")
    p_status.add_argument("order_id")
    p_status.set_defaults(func=cmd_status)

    p_trades = subparsers.add_parser("trades", help="Show trade flow")
    p_trades.add_argument("--hours", type=int, default=24)
    detail_group = p_trades.add_mutually_exclusive_group()
    detail_group.add_argument("--detailed", action="store_true")
    detail_group.add_argument("--short", action="store_true")
    p_trades.set_defaults(func=cmd_trades)

    p_run = subparsers.add_parser("run", help="Run scheduled analyze/trade phase")
    p_run.add_argument("--region", required=True, choices=["asia", "us"])
    p_run.add_argument("--phase", required=True, choices=["analyze", "trade"])
    dry_group = p_run.add_mutually_exclusive_group()
    dry_group.add_argument(
        "--dry",
        dest="dry",
        action="store_const",
        const=True,
        help="Force dry-run mode",
    )
    dry_group.add_argument(
        "--real",
        dest="dry",
        action="store_const",
        const=False,
        help="Override config and execute trades",
    )
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        args.func(args)
        return 0
    except Exception as exc:  # pragma: no cover - CLI diagnostics
        LOGGER.exception("Command failed: %s", exc)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
