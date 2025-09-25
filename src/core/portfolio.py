"""Portfolio construction helpers."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set

import requests

import config_dev3 as config

from . import balance, convert_api
from .convert_api import ConvertRoute
from .utils import DECIMAL_ZERO, decimal_from_any, rolling_log_directory

LOGGER = logging.getLogger(__name__)


LOG_ROOT = getattr(config, "CONVERT_LOG_ROOT", "/srv/dev3/logs/convert")

DENY_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR", "5L", "5S", "PERP")


@dataclass
class BalanceRow:
    asset: str
    amount: Decimal
    normalised: Optional[str]
    convertible: bool
    reason: str


@dataclass
class BalanceSnapshot:
    rows: List[BalanceRow]
    from_assets: Set[str]
    price_map: Dict[str, float]
    log_dir: Path

    def balances(self) -> Dict[str, Decimal]:
        return {r.normalised or r.asset: r.amount for r in self.rows if r.amount > 0}


@dataclass
class TargetAllocation:
    asset: str
    weight: float
    quote_amount: Decimal
    route: ConvertRoute
    min_quote: float
    max_quote: float
    candidate: Dict[str, Any]


@dataclass
class RebalanceAction:
    from_asset: str
    to_asset: str
    amount: Decimal
    route: ConvertRoute


def _normalise_asset(asset: str) -> Optional[str]:
    asset = (asset or "").upper().strip()
    if not asset:
        return None
    for suffix in DENY_SUFFIXES:
        if asset.endswith(suffix):
            return None
    if asset.startswith("LD") and asset.endswith("UP"):
        return None
    if asset.endswith("USDT") and asset != "USDT":
        prefix = asset[:-4]
        while prefix and prefix[0].isdigit():
            prefix = prefix[1:]
        if prefix:
            asset = prefix
    return asset


def _price_map_from_tickers() -> Dict[str, float]:
    try:
        payload = convert_api.binance_client.public_get("/api/v3/ticker/24hr")
    except requests.RequestException as exc:  # pragma: no cover - network
        LOGGER.warning("24hr ticker fetch failed: %s", exc)
        return {}
    prices: Dict[str, float] = {}
    if isinstance(payload, list):
        for row in payload:
            symbol = (row.get("symbol") or "").upper()
            if symbol.endswith("USDT") and len(symbol) > 4:
                base = symbol[:-4]
                try:
                    prices[base] = float(row.get("lastPrice") or 0.0)
                except (ValueError, TypeError):
                    continue
    return prices


def pre_analyze_balance_snapshot(ts: float | None = None) -> BalanceSnapshot:
    log_dir = rolling_log_directory(LOG_ROOT, ts)
    price_map = _price_map_from_tickers()
    rows: List[BalanceRow] = []
    from_assets: Set[str] = set()
    balances_map = balance.read_all("SPOT")
    for asset, amount in sorted((balances_map or {}).items()):
        dec = decimal_from_any(amount)
        if dec <= DECIMAL_ZERO:
            continue
        normalised = _normalise_asset(asset)
        convertible = False
        reason = ""
        if normalised is None:
            reason = "blocked_suffix"
        else:
            route = convert_api.route_exists(normalised, "USDT")
            if route:
                convertible = True
                from_assets.add(normalised)
            else:
                for hub in convert_api.HUB_ASSETS:
                    if convert_api.route_exists(normalised, hub):
                        convertible = True
                        from_assets.add(normalised)
                        break
                if not convertible:
                    reason = "no_convert_route"
        rows.append(
            BalanceRow(
                asset=_normalise_asset(asset) or asset,
                amount=dec,
                normalised=normalised,
                convertible=convertible,
                reason=reason,
            )
        )
    from_assets.add("USDT")
    csv_path = log_dir / "balance.pre.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["asset", "amount", "normalised", "convertible", "reason"])
        for row in rows:
            writer.writerow(
                [
                    row.asset,
                    float(row.amount),
                    row.normalised or "",
                    "yes" if row.convertible else "no",
                    row.reason,
                ]
            )
    return BalanceSnapshot(rows=rows, from_assets=from_assets, price_map=price_map, log_dir=log_dir)


def _base_weights(count: int) -> Sequence[float]:
    if count >= 3:
        return (0.6, 0.3, 0.1)
    if count == 2:
        return (0.7, 0.3)
    if count == 1:
        return (1.0,)
    return ()


def build_target_allocation(
    candidates: Sequence[Dict[str, Any]],
    total_equity: float,
    from_assets: Iterable[str],
) -> List[TargetAllocation]:
    from_assets_set = {asset.upper() for asset in from_assets}
    usable: List[tuple[Dict[str, Any], convert_api.ConvertRoute]] = []
    for candidate in candidates[:3]:
        base = (candidate.get("base") or "").upper()
        if not base:
            continue
        route = convert_api.preferred_route(from_assets_set, base)
        if not route:
            continue
        usable.append((dict(candidate), route))
    if not usable or total_equity <= 0:
        return []

    selected: List[TargetAllocation] = []
    pool = usable
    while pool:
        weights = _base_weights(len(pool))
        temp: List[TargetAllocation] = []
        removed = False
        for weight, item in zip(weights, pool):
            candidate, route = item
            min_quote = float(candidate.get("min_quote") or 0.0)
            max_quote = float(candidate.get("max_quote") or 0.0)
            quote_amount = Decimal(str(total_equity * weight))
            if min_quote > 0 and quote_amount < Decimal(str(min_quote)) and len(pool) > 1:
                pool = [c for c in pool if c is not item]
                removed = True
                break
            if max_quote > 0 and quote_amount > Decimal(str(max_quote)):
                quote_amount = Decimal(str(max_quote))
            temp.append(
                TargetAllocation(
                    asset=candidate.get("base"),
                    weight=float(weight),
                    quote_amount=quote_amount,
                    route=route,
                    min_quote=min_quote,
                    max_quote=max_quote,
                    candidate=candidate,
                )
            )
        if removed:
            continue
        selected = temp
        break
    return selected


def plan_rebalance(
    holdings: Mapping[str, Decimal],
    price_map: Mapping[str, float],
    targets: Sequence[TargetAllocation],
    threshold: float = 0.08,
) -> List[RebalanceAction]:
    actions: List[RebalanceAction] = []
    holdings_map: MutableMapping[str, Decimal] = {
        (k or "").upper(): decimal_from_any(v) for k, v in holdings.items()
    }
    total_equity = sum(
        float(amount) * (price_map.get(asset, 1.0) if asset != "USDT" else 1.0)
        for asset, amount in holdings_map.items()
    )
    if total_equity <= 0:
        return []

    for asset, amount in list(holdings_map.items()):
        if asset in ("USDT",) or any(t.asset == asset for t in targets):
            continue
        if amount <= DECIMAL_ZERO:
            continue
        route = convert_api.route_exists(asset, "USDT")
        if not route:
            continue
        actions.append(RebalanceAction(asset, "USDT", amount, route))
        usdt_notional = decimal_from_any(amount) * Decimal(str(price_map.get(asset, 0.0)))
        holdings_map[asset] = DECIMAL_ZERO
        holdings_map["USDT"] = holdings_map.get("USDT", DECIMAL_ZERO) + usdt_notional

    total_equity = sum(
        float(amount) * (price_map.get(asset, 1.0) if asset != "USDT" else 1.0)
        for asset, amount in holdings_map.items()
    )
    if total_equity <= 0:
        return actions

    for target in targets:
        asset = (target.asset or "").upper()
        price = Decimal(str(price_map.get(asset, 0.0) or 0.0))
        if price <= 0:
            continue
        current_units = holdings_map.get(asset, DECIMAL_ZERO)
        current_notional = current_units * price
        desired_notional = target.quote_amount
        diff = current_notional - desired_notional
        share_diff = float(diff) / total_equity if total_equity else 0.0
        if abs(share_diff) <= threshold:
            continue
        if diff > 0:
            amount_units = diff / price
            route = convert_api.route_exists(asset, "USDT")
            if not route or amount_units <= DECIMAL_ZERO:
                continue
            actions.append(RebalanceAction(asset, "USDT", amount_units, route))
            holdings_map[asset] = max(DECIMAL_ZERO, current_units - amount_units)
            holdings_map["USDT"] = holdings_map.get("USDT", DECIMAL_ZERO) + diff
        else:
            need_notional = -diff
            usdt_available = holdings_map.get("USDT", DECIMAL_ZERO)
            if usdt_available <= DECIMAL_ZERO:
                continue
            spend = min(usdt_available, need_notional)
            if spend <= DECIMAL_ZERO:
                continue
            route = convert_api.route_exists("USDT", asset)
            if not route:
                continue
            actions.append(RebalanceAction("USDT", asset, spend, route))
            holdings_map["USDT"] = max(DECIMAL_ZERO, usdt_available - spend)
            holdings_map[asset] = holdings_map.get(asset, DECIMAL_ZERO) + spend / price

    return actions
