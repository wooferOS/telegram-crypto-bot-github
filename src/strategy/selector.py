"""Candidate selection for Convert trades."""

from __future__ import annotations

import csv
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

import requests

import config_dev3 as config

from src.core import convert_api
from src.core.convert_api import ConvertRoute
from src.core.portfolio import BalanceSnapshot
from src.core.utils import clamp

LOGGER = logging.getLogger(__name__)


REGION_BIAS = {"us": 1.05, "asia": 1.03}
DEFAULT_MIN_VOLUME = getattr(config, "MIN_VOLUME_USDT", 5_000_000)
DEFAULT_MAX_SPREAD_BPS = getattr(config, "MAX_SPREAD_BPS", 5.0)
TOP_K = getattr(config, "TOP_K", 5)


@dataclass
class Candidate:
    rank: int
    symbol: str
    base: str
    score: float
    qvol: float
    chg: float
    spread_bps: float
    last_price: float
    route: ConvertRoute
    route_desc: str
    min_quote: float
    max_quote: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "symbol": self.symbol,
            "base": self.base,
            "score": self.score,
            "qVol": self.qvol,
            "chg": self.chg,
            "spread_bps": self.spread_bps,
            "last_price": self.last_price,
            "route": self.route_desc,
            "min_quote": self.min_quote,
            "max_quote": self.max_quote,
            "route_steps": [
                {"from": step.from_asset, "to": step.to_asset} for step in self.route.steps
            ],
        }


def _normalise_base(symbol: str) -> tuple[str, str]:
    symbol = symbol.upper()
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    return symbol, ""


def _route_description(route: ConvertRoute) -> str:
    if route.is_direct:
        return "direct"
    hubs = [step.to_asset for step in route.steps[:-1]]
    return "hub:" + "|".join(hubs)


def _compute_spread_bps(bid: float, ask: float) -> float:
    if bid <= 0 or ask <= 0:
        return 999.0
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 999.0
    return abs(ask - bid) / mid * 10_000


def _score_item(qvol: float, chg_pct: float, spread_bps: float, region: str) -> float:
    liquidity = math.log10(max(qvol, 0.0) + 1.0)
    momentum = 1.0 + clamp(chg_pct, -50.0, 50.0) / 100.0
    spread_penalty = 1.0 + (spread_bps / 10.0)
    base_score = max(0.0, liquidity * momentum / spread_penalty)
    bias = REGION_BIAS.get(region, 1.0)
    return base_score * bias


def _route_limits(route: ConvertRoute) -> tuple[float, float]:
    if not route.steps:
        return 0.0, 0.0
    first = route.steps[0]
    limits = convert_api.limits_for_pair(first.from_asset, first.to_asset)
    return float(limits.minimum), float(limits.maximum)


def select_candidates(
    region: str,
    snapshot: BalanceSnapshot,
    min_volume: float = DEFAULT_MIN_VOLUME,
    max_spread_bps: float = DEFAULT_MAX_SPREAD_BPS,
    top_k: int = TOP_K,
) -> List[Candidate]:
    try:
        tickers = convert_api.binance_client.public_get("/api/v3/ticker/24hr")
    except requests.RequestException as exc:  # pragma: no cover - network
        LOGGER.error("ticker/24hr fetch failed: %s", exc)
        return []
    from_assets = snapshot.from_assets
    rejections: Dict[str, int] = {}
    candidates: List[Candidate] = []

    if not isinstance(tickers, list):
        return []

    for row in tickers:
        symbol = (row.get("symbol") or "").upper()
        base, quote = _normalise_base(symbol)
        if quote != "USDT":
            continue
        last_price = float(row.get("lastPrice") or 0.0)
        qvol = float(row.get("quoteVolume") or 0.0)
        if qvol < min_volume:
            rejections["low_volume"] = rejections.get("low_volume", 0) + 1
            continue
        bid = float(row.get("bidPrice") or 0.0)
        ask = float(row.get("askPrice") or 0.0)
        spread_bps = _compute_spread_bps(bid, ask)
        if spread_bps > max_spread_bps:
            rejections["wide_spread"] = rejections.get("wide_spread", 0) + 1
            continue
        route = convert_api.preferred_route(from_assets, base)
        if not route:
            rejections["no_route"] = rejections.get("no_route", 0) + 1
            continue
        chg_pct = float(row.get("priceChangePercent") or 0.0)
        score = _score_item(qvol, chg_pct, spread_bps, region)
        min_quote, max_quote = _route_limits(route)
        candidate = Candidate(
            rank=0,
            symbol=symbol,
            base=base,
            score=score,
            qvol=qvol,
            chg=chg_pct,
            spread_bps=spread_bps,
            last_price=last_price,
            route=route,
            route_desc=_route_description(route),
            min_quote=min_quote,
            max_quote=max_quote,
        )
        candidates.append(candidate)

    candidates.sort(key=lambda c: c.score, reverse=True)
    selected = candidates[: top_k or len(candidates)]
    for idx, cand in enumerate(selected, start=1):
        cand.rank = idx

    summary_path = snapshot.log_dir / "summary.txt"
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write(f"Region={region} Total={len(selected)}\n")
        if rejections:
            fh.write("Rejections:" + "\n")
            for key, val in sorted(rejections.items()):
                fh.write(f"  {key}: {val}\n")

    csv_path = snapshot.log_dir / f"candidates.{region}.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "rank",
                "symbol",
                "base",
                "score",
                "qVol",
                "chg",
                "spread_bps",
                "last_price",
                "route",
                "min_quote",
                "max_quote",
            ]
        )
        for cand in selected:
            writer.writerow(
                [
                    cand.rank,
                    cand.symbol,
                    cand.base,
                    cand.score,
                    cand.qvol,
                    cand.chg,
                    cand.spread_bps,
                    cand.last_price,
                    cand.route_desc,
                    cand.min_quote,
                    cand.max_quote,
                ]
            )

    json_path = snapshot.log_dir / f"candidates.{region}.json"
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump([cand.as_dict() for cand in selected], fh, indent=2)

    return selected
