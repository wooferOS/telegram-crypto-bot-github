"""Candidate selection for Convert trades."""


from __future__ import annotations
import logging

LOGGER = logging.getLogger(__name__)

import config_dev3 as config
TARGET_QUOTE = getattr(config, "TARGET_QUOTE", "USDT").upper()


def _load_exchange_info() -> dict:
    """
    Повертає dict з ключем "symbols".
    1) /sapi/v1/convert/exchangeInfo (SIGNED) може бути list або dict.
    2) Фолбек: /api/v3/exchangeInfo (PUBLIC).
    Завжди нормалізуємо до {"symbols": [...]}.
    """
    data = None
    try:
        from src.core import binance_client
        data = binance_client.get("/sapi/v1/convert/exchangeInfo", {}, signed=True)
    except Exception as _exc:  # pragma: no cover - network
        try:
            LOGGER.warning("exchangeInfo fetch skipped: %s", _exc)
        except Exception:
            pass

    # Нормалізація convert-відповіді
    if isinstance(data, dict) and "symbols" in data:
        return data
    if isinstance(data, list):
        return {"symbols": data}

    # Публічний фолбек
    try:
        from src.core import convert_api
        publ = convert_api.binance_client.public_get("/api/v3/exchangeInfo", timeout=6)
        if isinstance(publ, list):
            return {"symbols": publ}
        if isinstance(publ, dict) and "symbols" in publ:
            return publ
    except Exception:
        pass

    return {"symbols": []}


def _collect_pairs(ex: dict) -> list[str]:
    """
    Витягує коди пар для TARGET_QUOTE з різних схем:
    - {symbol, status, quoteAsset}
    - {fromAsset, toAsset, status}
    - стислі ключі {s, b, q, st}
    - або просто рядки "BTCUSDT"
    """
    out: list[str] = []
    for rec in (ex or {}).get("symbols", []) or []:
        if isinstance(rec, str):
            sym = rec.upper()
            if sym.endswith(TARGET_QUOTE):
                out.append(sym)
            continue
        if not isinstance(rec, dict):
            continue

        base  = str(rec.get("baseAsset") or rec.get("fromAsset") or rec.get("b") or "").upper()
        quote = str(rec.get("quoteAsset") or rec.get("toAsset")   or rec.get("q") or "").upper()
        sym   = str(rec.get("symbol")    or rec.get("s")          or "").upper()
        if not sym and base and quote:
            sym = base + quote

        st = rec.get("status") or rec.get("st")
        is_trading = (st in ("TRADING", "ENABLED", None))

        if sym and (quote == TARGET_QUOTE or sym.endswith(TARGET_QUOTE)) and is_trading:
            out.append(sym)

    # Дедуп з порядком
    seen, res = set(), []
    for s in out:
        if s not in seen:
            seen.add(s); res.append(s)
    return res


# --- ПІДНІМАЄМО сюди, щоб _usdt_symbols бачив цю функцію ---
def _fetch24_multi(symbols: list[str]) -> dict[str, dict]:
    """Fetch many 24hr tickers in one call. Returns {SYMBOL: payload}.
    - 1ша спроба: /api/v3/ticker/24hr через наш клієнт (PATH)
    - 2га спроба: абсолютний https://data-api.binance.vision/... через requests
    - Якщо все впало — {}
    """
    import json
    out: dict[str, dict] = {}
    symbols = [s for s in symbols if s]
    if not symbols:
        return out

    params = {"symbols": json.dumps(symbols, separators=(",", ":"))}

    # primary: наш клієнт (PATH)
    try:
        from src.core import convert_api
        data = convert_api.binance_client.public_get("/api/v3/ticker/24hr", params=params, timeout=6)
        for d in data or []:
            sym = (d.get("symbol") or "").upper()
            if sym:
                out[sym] = d
        if out:
            return out
    except Exception:
        pass

    # fallback: абсолютний URL через requests
    try:
        import requests
        url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        # Санітайзер на випадок випадкових // у майбутніх змiнах
        if url.startswith("//"):
            url = "https:" + url
        r = requests.get(url, params=params, timeout=6)
        if r.ok:
            data = r.json()
            if isinstance(data, dict):
                data = [data]
            for d in data or []:
                sym = (d.get("symbol") or "").upper()
                if sym:
                    out[sym] = d
            if out:
                return out
    except Exception:
        pass

    return {}

def _fetch24_cached(s: str):
    """
    Отримує один 24hr тикер по символу.
    1) Публічний /api/v3/ticker/24hr через наш клієнт (PATH).
    2) Абсолютний https://data-api.binance.vision/... через requests, якщо клієнт впав.
    Повертає dict або None.
    """
    try:
        from src.core import convert_api
        params = {"symbol": s}
        d = convert_api.binance_client.public_get("/api/v3/ticker/24hr", params=params, timeout=6)
        if isinstance(d, list) and d:
            d = d[0]
        return d if isinstance(d, dict) else None
    except Exception:
        pass
    try:
        import requests
        url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        r = requests.get(url, params={"symbol": s}, timeout=6)
        if r.ok:
            d = r.json()
            if isinstance(d, list) and d:
                d = d[0]
            return d if isinstance(d, dict) else None
    except Exception:
        return None
    return None


    params = {"symbols": json.dumps(symbols, separators=(",", ":"))}
    try:
        from src.core import convert_api
        data = convert_api.binance_client.public_get("/api/v3/ticker/24hr", params=params, timeout=6)
        for d in data or []:
            sym = (d.get("symbol") or "").upper()
            if sym:
                out[sym] = d
        if out:
            return out
    except Exception:
        pass

    # Абсолютний фолбек — requests напряму, щоб не ламати URL
    try:
        import requests
        url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        r = requests.get(url, params=params, timeout=6)
        if r.ok:
            data = r.json()
            for d in data or []:
                sym = (d.get("symbol") or "").upper()
                if sym:
                    out[sym] = d
    except Exception:
        # тихо повертаємо {}, сортування піде алфавітом
        return {}

    return out
    params = {"symbols": json.dumps(symbols, separators=(",", ":"))}
    try:
        data = convert_api.binance_client.public_get("/api/v3/ticker/24hr", params=params, timeout=6)
    except Exception:
        data = convert_api.binance_client.public_get(
            "https://data-api.binance.vision/api/v3/ticker/24hr", params=params, timeout=6
        )
    for d in data or []:
        sym = (d.get("symbol") or "").upper()
        if sym:
            out[sym] = d
    return out
# ------------------------------------------------------------


def _usdt_symbols(limit: int = 300) -> list[str]:
    """
    Універсальний відбір пар для TARGET_QUOTE без хардкодів.
    Якщо 24h дані доступні — сортуємо за quoteVolume; інакше — алфавітом.
    """
    try:
        ex = _load_exchange_info()
        symbols = _collect_pairs(ex)
        if not symbols:
            return []
        tick = _fetch24_multi(symbols[:300])

        def qvol(s: str) -> float:
            d = tick.get(s) or {}
            try:
                return float(d.get("quoteVolume") or 0.0)
            except Exception:
                return 0.0

        if tick:
            symbols.sort(key=lambda s: (-qvol(s), s))
        else:
            symbols.sort()
        return symbols[:limit]
    except Exception as _exc:  # pragma: no cover - network
        try:
            LOGGER.warning("symbols build failed: %s", _exc)
        except Exception:
            pass
        return []

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
SHORTLIST_MULT = getattr(config, "SHORTLIST_MULT", 2)


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
            "route_steps": [{"from": step.from_asset, "to": step.to_asset} for step in self.route.steps],
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
        syms = _usdt_symbols()
        tickers: list[dict] = []
        for s_ in syms:
            d = _fetch24_cached(s_)
            if isinstance(d, dict):
                tickers.append(d)
    except requests.RequestException as exc:  # pragma: no cover - network
        LOGGER.error("ticker/24hr fetch failed: %s", exc)
        return []
    from_assets = snapshot.from_assets
    rejections: Dict[str, int] = {}
    candidates: List[Candidate] = []
    pr_calls = 0
    # 1) Збираємо items без роутингу
    items: list[dict] = []
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
        chg_pct = float(row.get("priceChangePercent") or 0.0)
        score = _score_item(qvol, chg_pct, spread_bps, region)
        items.append(
            {
                "base": base,
                "symbol": symbol,
                "last_price": last_price,
                "qvol": qvol,
                "chg_pct": chg_pct,
                "spread_bps": spread_bps,
                "score": score,
            }
        )
    # 2) Сортуємо за score і беремо shortlist (~ top_k * SHORTLIST_MULT)
    items.sort(key=lambda x: x["score"], reverse=True)
    _tk = top_k or len(items)
    n = min(len(items), _tk * SHORTLIST_MULT)
    shortlist = items[:n]

    # 3) Роутимо ТІЛЬКИ shortlist і добираємо до top_k
    for it in shortlist:
        base = it["base"]
        route = convert_api.preferred_route(from_assets, base)
        pr_calls += 1
        if not route:
            rejections["no_route"] = rejections.get("no_route", 0) + 1
            continue
        min_quote, max_quote = _route_limits(route)
        candidate = Candidate(
            rank=0,
            symbol=it["symbol"],
            base=base,
            score=it["score"],
            qvol=it["qvol"],
            chg=it["chg_pct"],
            spread_bps=it["spread_bps"],
            last_price=it["last_price"],
            route=route,
            route_desc=_route_description(route),
            min_quote=min_quote,
            max_quote=max_quote,
        )
        candidates.append(candidate)
        if top_k and len(candidates) >= top_k:
            break

    candidates.sort(key=lambda c: c.score, reverse=True)
    selected = candidates[: top_k or len(candidates)]
    for idx, cand in enumerate(selected, start=1):
        cand.rank = idx

    summary_path = snapshot.log_dir / "summary.txt"
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write(f"Region={region} Total={len(selected)} pr_calls={pr_calls}\n")
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
