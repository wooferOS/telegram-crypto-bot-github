"""Phase orchestrator for Convert automation."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Dict, List

from src.core import balance
from src.core import guard as guard_module
from src.core import portfolio, position
from src.core.ensure_invested import execute_plan
from src.strategy.selector import select_candidates

LOGGER = logging.getLogger(__name__)


def _total_equity(snapshot: portfolio.BalanceSnapshot) -> float:
    total = 0.0
    for row in snapshot.rows:
        asset = (row.normalised or row.asset).upper()
        amount = float(row.amount)
        if asset == "USDT":
            price = 1.0
        else:
            price = snapshot.price_map.get(asset, 0.0)
        total += amount * price
    return total


def _load_candidates(snapshot: portfolio.BalanceSnapshot, region: str) -> List[Dict[str, object]]:
    path = snapshot.log_dir / f"candidates.{region}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    selected = select_candidates(region, snapshot)
    data = [cand.as_dict() for cand in selected]
    path.write_text(json.dumps(data, indent=2))
    return data


def _holdings_from_snapshot(snapshot: portfolio.BalanceSnapshot) -> Dict[str, Decimal]:
    holdings: Dict[str, Decimal] = {}
    for row in snapshot.rows:
        key = (row.normalised or row.asset).upper()
        holdings[key] = row.amount
    return holdings


def run_analyze(region: str, snapshot: portfolio.BalanceSnapshot) -> None:
    LOGGER.info("Running analyze for region %s", region)
    select_candidates(region, snapshot)


def run_trade(region: str, snapshot: portfolio.BalanceSnapshot, dry_run: bool) -> None:
    LOGGER.info("Running trade for region %s dry_run=%s", region, dry_run)
    candidates = _load_candidates(snapshot, region)
    total_equity = _total_equity(snapshot)
    targets = portfolio.build_target_allocation(candidates, total_equity, snapshot.from_assets)
    holdings = _holdings_from_snapshot(snapshot)
    actions = portfolio.plan_rebalance(holdings, snapshot.price_map, targets)
    execute_plan(region, actions, snapshot.log_dir, dry_run=dry_run)
    summary_path = snapshot.log_dir / "summary.txt"
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write(f"TRADE region={region} actions={len(actions)} dry_run={int(dry_run)}\n")
    if dry_run or not actions:
        return
    new_balances = balance.read_all("SPOT")
    state = position.load()
    updated = position.sync_from_balances(new_balances, snapshot.price_map, state)
    position.save(updated)


def run_guard(region: str, snapshot: portfolio.BalanceSnapshot, dry_run: bool) -> None:
    LOGGER.info("Running guard for region %s", region)
    state = position.load()
    result = guard_module.run_guard(region, snapshot, state, dry_run=dry_run)
    summary_path = snapshot.log_dir / "summary.txt"
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write(
            "GUARD region={region} triggered={triggered} portfolio={portfolio} assets={assets}\n".format(
                region=region,
                triggered=int(result.triggered),
                portfolio=int(result.portfolio_trigger),
                assets=",".join(result.asset_triggers),
            )
        )


def run(region: str, phase: str, dry_run: bool) -> None:
    snapshot = portfolio.pre_analyze_balance_snapshot()
    phase = phase.lower()
    if phase == "pre-analyze":
        LOGGER.info("Pre-analyze complete for region %s", region)
        return
    if phase == "analyze":
        run_analyze(region, snapshot)
        return
    if phase == "trade":
        run_trade(region, snapshot, dry_run)
        return
    if phase == "guard":
        run_guard(region, snapshot, dry_run)
        return
    raise ValueError(f"Unsupported phase {phase}")
