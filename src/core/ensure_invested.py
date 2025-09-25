"""Execute Convert rebalance plan with anti-spam safeguards."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List, Sequence

from . import convert_api
from .portfolio import RebalanceAction
from .utils import decimal_from_any, ensure_parent, now_ms

LOGGER = logging.getLogger(__name__)


def _load_history(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    if isinstance(data, list):
        return data
    return []


def _save_history(path: Path, entries: Sequence[dict]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(list(entries), separators=(",", ":")))


def _append_trade_log(path: Path, text: str) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def execute_plan(
    region: str,
    actions: Sequence[RebalanceAction],
    log_dir: Path,
    wallet: str = "SPOT",
    dry_run: bool = False,
    tolerance: float = 0.01,
) -> List[dict]:
    """Execute rebalance actions returning Convert responses."""

    responses: List[dict] = []
    history_path = log_dir / "convert_history.json"
    history = _load_history(history_path)
    trade_log_path = log_dir / f"trade.{region}.log"

    convert_api.reset_dedup_cache()

    for action in actions:
        amount_dec = decimal_from_any(action.amount)
        if amount_dec <= Decimal("0"):
            continue
        route = action.route
        route_desc = " -> ".join(f"{step.from_asset}->{step.to_asset}" for step in route.steps)
        log_prefix = f"{datetime.utcnow().isoformat()}Z {region}"
        if dry_run:
            text = f"{log_prefix} DRY {route_desc} amount={float(amount_dec)}"
            _append_trade_log(trade_log_path, text)
            history.append(
                {
                    "ts": now_ms(),
                    "region": region,
                    "route": route_desc,
                    "amount": float(amount_dec),
                    "wallet": wallet,
                    "status": "dry_run",
                }
            )
            continue
        try:
            exec_responses = convert_api.execute_unique(route, amount_dec, wallet, tolerance)
            if not exec_responses:
                continue
        except Exception as exc:  # pragma: no cover - network
            LOGGER.error("Convert execution failed for %s: %s", route_desc, exc)
            history.append(
                {
                    "ts": now_ms(),
                    "region": region,
                    "route": route_desc,
                    "amount": float(amount_dec),
                    "wallet": wallet,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue

        for payload in exec_responses:
            quote = payload.get("quote", {}) if isinstance(payload, dict) else {}
            order_id = payload.get("orderId") if isinstance(payload, dict) else None
            quote_id = quote.get("quoteId") if isinstance(quote, dict) else None
            to_amount = quote.get("toAmount") or quote.get("toAmountExpected")
            entry = {
                "ts": now_ms(),
                "region": region,
                "route": route_desc,
                "amount": float(amount_dec),
                "wallet": wallet,
                "orderId": order_id,
                "quoteId": quote_id,
                "toAmount": to_amount,
                "status": "executed",
            }
            history.append(entry)
            responses.append(payload)
            text = (
                f"{log_prefix} EXEC {route_desc} amount={float(amount_dec)} "
                f"order={order_id} quote={quote_id} toAmount={to_amount}"
            )
            _append_trade_log(trade_log_path, text)

    _save_history(history_path, history)
    return responses
