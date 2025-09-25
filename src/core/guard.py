"""Panic guard logic (15% drawdown rules)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from . import balance, convert_api
from .ensure_invested import execute_plan
from .portfolio import BalanceSnapshot, RebalanceAction
from .position import PositionState, save as save_position, sync_from_balances

LOGGER = logging.getLogger(__name__)


@dataclass
class GuardResult:
    triggered: bool
    asset_triggers: List[str]
    portfolio_trigger: bool


def run_guard(
    region: str,
    snapshot: BalanceSnapshot,
    position_state: PositionState,
    dry_run: bool = False,
) -> GuardResult:
    price_map = snapshot.price_map
    actions: List[RebalanceAction] = []
    triggered_assets: List[str] = []
    portfolio_trigger = False

    for asset, amount in position_state.assets.items():
        if asset == "USDT" or amount <= 0:
            continue
        peak_price = position_state.peaks.get(asset, 0.0)
        last_price = price_map.get(asset, 0.0)
        if peak_price <= 0 or last_price <= 0:
            continue
        if last_price <= peak_price * 0.85:
            route = convert_api.route_exists(asset, "USDT")
            if not route:
                continue
            actions.append(RebalanceAction(asset, "USDT", amount, route))
            triggered_assets.append(asset)

    equity_now = position_state.equity(price_map)
    if position_state.portfolio_peak > 0 and equity_now <= position_state.portfolio_peak * 0.85:
        portfolio_trigger = True
        actions = []
        triggered_assets = []
        for asset, amount in position_state.assets.items():
            if asset == "USDT" or amount <= 0:
                continue
            route = convert_api.route_exists(asset, "USDT")
            if not route:
                continue
            actions.append(RebalanceAction(asset, "USDT", amount, route))
            triggered_assets.append(asset)

    if not actions:
        return GuardResult(False, [], False)

    execute_plan(region, actions, snapshot.log_dir, dry_run=dry_run)

    if not dry_run:
        balances = balance.read_all("SPOT")
        new_state = sync_from_balances(balances, price_map, position_state)
        save_position(new_state)

    return GuardResult(True, triggered_assets, portfolio_trigger)
