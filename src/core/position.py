"""Portfolio position persistence and peak tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, Mapping

import config_dev3 as config

from .utils import DECIMAL_ZERO, decimal_from_any, ensure_parent, now_ms


DEFAULT_STATE_PATH = Path(
    getattr(config, "POSITION_STATE_PATH", "/srv/dev3/state/position.json")
)


def _normalise_asset(asset: str) -> str:
    return (asset or "").upper().strip()


def _price_for(asset: str, price_map: Mapping[str, float]) -> float:
    if asset == "USDT":
        return 1.0
    return float(price_map.get(asset, 0.0) or 0.0)


@dataclass
class PositionState:
    assets: Dict[str, Decimal] = field(default_factory=dict)
    peaks: Dict[str, float] = field(default_factory=dict)
    portfolio_peak: float = 0.0
    ts: int = field(default_factory=now_ms)

    def equity(self, price_map: Mapping[str, float]) -> float:
        total = 0.0
        for asset, amount in self.assets.items():
            total += float(amount) * _price_for(asset, price_map)
        return total

    def update_peaks(self, price_map: Mapping[str, float]) -> None:
        for asset, amount in self.assets.items():
            if amount <= 0:
                continue
            price = _price_for(asset, price_map)
            if price <= 0:
                continue
            self.peaks[asset] = max(self.peaks.get(asset, 0.0), price)
        equity_now = self.equity(price_map)
        self.portfolio_peak = max(self.portfolio_peak, equity_now)
        self.ts = now_ms()


def load(path: Path | None = None) -> PositionState:
    path = path or DEFAULT_STATE_PATH
    if not path.exists():
        return PositionState()
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return PositionState()
    assets: Dict[str, Decimal] = {}
    for asset, amount in (payload.get("assets") or {}).items():
        value = decimal_from_any(amount)
        if value > 0:
            assets[_normalise_asset(asset)] = value
    peaks = {
        _normalise_asset(k): float(v)
        for k, v in (payload.get("peaks") or {}).items()
        if v is not None
    }
    return PositionState(
        assets=assets,
        peaks=peaks,
        portfolio_peak=float(payload.get("portfolio_peak", 0.0) or 0.0),
        ts=int(payload.get("ts", now_ms())),
    )


def save(state: PositionState, path: Path | None = None) -> None:
    path = path or DEFAULT_STATE_PATH
    ensure_parent(path)
    payload = {
        "assets": {k: float(v) for k, v in state.assets.items()},
        "peaks": {k: float(v) for k, v in state.peaks.items()},
        "portfolio_peak": float(state.portfolio_peak),
        "ts": int(state.ts),
    }
    path.write_text(json.dumps(payload, separators=(",", ":")))


def sync_from_balances(
    balances: Mapping[str, Decimal | float | str],
    price_map: Mapping[str, float],
    previous: PositionState | None = None,
) -> PositionState:
    state = previous or PositionState()
    state.assets = {
        _normalise_asset(asset): decimal_from_any(amount)
        for asset, amount in balances.items()
        if decimal_from_any(amount) > DECIMAL_ZERO
    }
    state.update_peaks(price_map)
    return state


def clear(path: Path | None = None) -> None:
    path = path or DEFAULT_STATE_PATH
    if path.exists():
        path.unlink()
