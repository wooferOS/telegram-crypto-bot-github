"""Command line interface for Binance Convert automation."""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Dict

from src import app
from src.core import balance, convert_api, utils
from src.core.convert_api import ConvertError

LOGGER = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_info(args: argparse.Namespace) -> None:
    info = convert_api.get_exchange_info(args.from_asset, args.to_asset)
    payload = info.get("data") if isinstance(info, dict) else info
    if isinstance(payload, dict):
        min_amount = payload.get("fromAssetMinAmount")
        max_amount = payload.get("fromAssetMaxAmount")
    else:
        min_amount = max_amount = None

    print(f"Pair: {args.from_asset.upper()}/{args.to_asset.upper()}")
    if min_amount is not None:
        print(f"Min amount: {min_amount}")
    if max_amount not in (None, "0", 0):
        print(f"Max amount: {max_amount}")

    for wallet in ("SPOT", "FUNDING"):
        from_free = balance.read_free(args.from_asset, wallet)
        to_free = balance.read_free(args.to_asset, wallet)
        print(
            f"{wallet}: {args.from_asset.upper()}={from_free} {args.to_asset.upper()}={to_free}"
        )


def _print_quote(result: Dict[str, Any]) -> None:
    print(
        f"Quote {result.get('fromAsset')}→{result.get('toAsset')} "
        f"wallet={result.get('wallet')} amount={result.get('amount')}"
    )
    price = result.get("price") or result.get("ratio")
    if price:
        print(f"Price: {price}")
    if result.get("expireTime"):
        print(f"Expires: {result['expireTime']}")
    if result.get("insufficient"):
        print(
            "Warning: insufficient balance; available="
            f"{result.get('available')}"
        )


def cmd_quote(args: argparse.Namespace) -> None:
    try:
        result = app.quote_once(
            args.from_asset,
            args.to_asset,
            args.amount,
            args.wallet,
        )
    except ConvertError as exc:
        print(f"Quote error: {exc}", file=sys.stderr)
        sys.exit(1)
    _print_quote(result)


def cmd_now(args: argparse.Namespace) -> None:
    dry_run = args.dry_run
    try:
        result = app.convert_once(
            args.from_asset,
            args.to_asset,
            args.amount,
            args.wallet,
            dry_run=dry_run,
        )
    except ConvertError as exc:
        print(f"Conversion error: {exc}", file=sys.stderr)
        sys.exit(1)

    if result.get("status") == "SKIPPED":
        print("Insufficient balance; conversion skipped")
        return

    _print_quote(result)
    if dry_run:
        print("Dry run — quote only, no acceptQuote issued")
        return

    accept = result.get("accept")
    if isinstance(accept, dict):
        order_id = accept.get("orderId")
        print(f"Order ID: {order_id}")
    status = result.get("orderStatus")
    if isinstance(status, dict):
        print(f"Status: {status.get('status')}")


def cmd_status(args: argparse.Namespace) -> None:
    status = convert_api.get_order_status(args.order_id)
    if isinstance(status, dict):
        print(f"Order {args.order_id} -> {status.get('status')}")
        if status.get("price"):
            print(f"Price: {status['price']}")
        if status.get("toAmount"):
            print(f"Received: {status['toAmount']}")
    else:
        print(status)


def cmd_trades(args: argparse.Namespace) -> None:
    end_ms = utils.now_ms()
    start_ms = end_ms - int(args.hours * 3600 * 1000)
    trades = convert_api.get_trade_flow(start_ms, end_ms, limit=args.limit)
    items = trades.get("list") if isinstance(trades, dict) else None
    if not isinstance(items, list):
        print("No trade data available")
        return
    print(f"Trades in last {args.hours}h: {len(items)}")
    if args.detailed:
        for entry in items:
            order_id = entry.get("orderId")
            status = entry.get("status")
            price = entry.get("price")
            amount = entry.get("fromAmount")
            print(
                f"#{order_id} {status} amount={amount} price={price}"
            )


def cmd_run(args: argparse.Namespace) -> None:
    app.run(args.region, args.phase, dry_run=args.dry)


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
    p_now.add_argument("--dry-run", dest="dry_run", action="store_true")
    p_now.set_defaults(func=cmd_now)

    p_status = subparsers.add_parser("status", help="Fetch order status")
    p_status.add_argument("order_id")
    p_status.set_defaults(func=cmd_status)

    p_trades = subparsers.add_parser("trades", help="Show trade flow")
    p_trades.add_argument("--hours", type=int, default=24)
    p_trades.add_argument("--limit", type=int, default=100)
    p_trades.add_argument("--detailed", action="store_true")
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
        help="Execute trades regardless of config",
    )
    p_run.set_defaults(func=cmd_run, dry=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        args.func(args)
        return 0
    except ConvertError as exc:
        LOGGER.error("Convert error: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover - CLI diagnostics
        LOGGER.exception("Command failed: %s", exc)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
