"""Command line interface for Convert automation helpers."""

from __future__ import annotations

import src.boot_guard  # patches requests acceptQuote guard  # noqa: F401

import argparse
import logging
import sys
from decimal import Decimal

import config_dev3 as config
from src import app
from src.core import balance, convert_api, utils

LOGGER = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def _format_decimal(value: Decimal) -> str:
    return utils.floor_str_8(Decimal(value))


def _print_header(args: argparse.Namespace) -> None:
    w = (getattr(args, "wallet", "SPOT") or "SPOT").upper()
    fa = getattr(args, "from_asset", "?")
    ta = getattr(args, "to_asset", "?")
    amt = getattr(args, "amount", "?")
    print(f"Quote {str(fa).upper()}→{str(ta).upper()} wallet={w} amount={amt}")


def _print_quote(quote: dict) -> None:
    ratio = quote.get("ratio") or quote.get("price")
    if ratio is not None:
        print(f"Ratio: {ratio}")
    to_amount = quote.get("toAmount") or quote.get("toAmountExpected")
    if to_amount is not None:
        print(f"To amount: {to_amount}")
    expire = quote.get("expireTime")
    if expire:
        print(f"Expires: {expire}")
    if quote.get("insufficient"):
        print(f"Warning: insufficient balance (available={quote.get('available')})")


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
        from_free = _format_decimal(balance.read_free(args.from_asset, wallet))
        to_free = _format_decimal(balance.read_free(args.to_asset, wallet))
        print(f"{wallet}: {args.from_asset.upper()}={from_free} {args.to_asset.upper()}={to_free}")


def cmd_quote(args: argparse.Namespace) -> None:
    quote = convert_api.get_quote(args.from_asset, args.to_asset, args.amount, args.wallet)
    print(
        "Quote {}→{} wallet={} amount={}".format(
            args.from_asset, args.to_asset, (args.wallet or "SPOT").upper(), args.amount
        )
    )
    _print_quote(quote)


def _determine_dry_run(value: int | None) -> bool:
    if value is None:
        return bool(getattr(config, "DRY_RUN", 0))
    return bool(value)


def cmd_now(args: argparse.Namespace) -> None:
    dry_run = _determine_dry_run(args.dry_run)
    quote = convert_api.get_quote(args.from_asset, args.to_asset, args.amount, args.wallet)
    print(
        "Quote {}→{} wallet={} amount={}".format(
            args.from_asset, args.to_asset, (args.wallet or "SPOT").upper(), args.amount
        )
    )
    _print_quote(quote)

    if quote.get("insufficient"):
        print("Conversion skipped: insufficient balance")
        return

    quote_id = quote.get("quoteId")
    if not quote_id:
        # print("Quote did not return quoteId; aborting", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        # print("Dry run mode — acceptQuote not executed")
        return

    accept = convert_api.accept_quote(str(quote_id))
    order_id = accept.get("orderId") if isinstance(accept, dict) else None
    print(f"Order ID: {order_id}")
    if not order_id:
        return
    status = convert_api.order_status(order_id)
    print(f"Status: {status.get('status')}")
    if status.get("toAmount"):
        print(f"To amount: {status['toAmount']}")


def cmd_status(args: argparse.Namespace) -> None:
    status = convert_api.order_status(args.order_id)
    if isinstance(status, dict):
        print(f"Order {args.order_id}: {status.get('status')}")
        if status.get("price"):
            print(f"Price: {status['price']}")
        if status.get("toAmount"):
            print(f"To amount: {status['toAmount']}")
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
            from_amount = entry.get("fromAmount")
            price = entry.get("price")
            print(f"#{order_id} {status} amount={from_amount} price={price}")


def cmd_run(args: argparse.Namespace) -> None:
    dry_run = _determine_dry_run(args.dry_run)
    app.run(args.region, args.phase, dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="Show limits and balances")
    p_info.add_argument("from_asset")
    p_info.add_argument("to_asset")
    p_info.set_defaults(func=cmd_info)

    p_quote = sub.add_parser("quote", help="Fetch a convert quote")
    p_quote.add_argument("from_asset")
    p_quote.add_argument("to_asset")
    p_quote.add_argument("amount")
    p_quote.add_argument("--wallet", default="SPOT", choices=["SPOT", "FUNDING"])
    p_quote.set_defaults(func=cmd_quote)

    p_now = sub.add_parser("now", help="Execute a conversion immediately")
    p_now.add_argument("from_asset")
    p_now.add_argument("to_asset")
    p_now.add_argument("amount")
    p_now.add_argument("--wallet", default="SPOT", choices=["SPOT", "FUNDING"])
    p_now.add_argument("--dry-run", dest="dry_run", type=int, choices=[0, 1], default=None)
    p_now.set_defaults(func=cmd_now)

    p_status = sub.add_parser("status", help="Check order status")
    p_status.add_argument("order_id")
    p_status.set_defaults(func=cmd_status)

    p_trades = sub.add_parser("trades", help="Show trade history")
    p_trades.add_argument("--hours", type=int, default=24)
    p_trades.add_argument("--limit", type=int, default=100)
    p_trades.add_argument("--detailed", action="store_true")
    p_trades.set_defaults(func=cmd_trades)

    p_run = sub.add_parser("run", help="Invoke auto-cycle phase")
    p_run.add_argument("--region", required=True, choices=["asia", "us"])
    p_run.add_argument(
        "--phase",
        required=True,
        choices=["pre-analyze", "analyze", "trade", "guard"],
    )
    p_run.add_argument("--dry-run", dest="dry_run", type=int, choices=[0, 1], default=None)
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        args.func(args)
    except Exception as exc:  # pragma: no cover - top level guard
        LOGGER.exception("Command failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
