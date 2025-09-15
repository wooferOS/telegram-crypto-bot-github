"""Helpers for spot analysis and Convert integration."""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple


def spot_to_convert_assets(symbol_info: Dict[str, str]) -> Tuple[str, str]:
    """Map a Spot symbol entry to Convert assets.

    Parameters
    ----------
    symbol_info : dict
        Entry from ``exchangeInfo.symbols``.

    Returns
    -------
    tuple
        ``(fromAsset, toAsset)`` usable with Convert API.
    """
    base = symbol_info.get("baseAsset")
    quote = symbol_info.get("quoteAsset")
    if not base or not quote:
        raise ValueError("symbol_info missing baseAsset/quoteAsset")
    return base, quote


def rank_symbols(
    stats: Sequence[Dict[str, float | str]],
    klines: Dict[str, Sequence[Sequence[float | str]]],
    min_quote_volume: float = 0.0,
) -> List[str]:
    """Rank symbols by 24h stats and momentum.

    ``stats`` is an iterable of dicts from ``ticker/24hr`` with at least
    ``symbol``, ``priceChangePercent`` and ``quoteVolume`` fields.
    ``klines`` maps symbol -> recent candle data (last two candles suffices).
    """
    ranked: List[Tuple[float, str]] = []
    for item in stats:
        symbol = str(item.get("symbol", ""))
        if not symbol:
            continue
        try:
            vol = float(item.get("quoteVolume", 0))
        except Exception:
            vol = 0.0
        if vol < min_quote_volume:
            continue
        try:
            change = float(item.get("priceChangePercent", 0))
        except Exception:
            change = 0.0
        k = klines.get(symbol, [])
        momentum = 0.0
        if len(k) >= 2:
            try:
                prev_close = float(k[-2][4])
                close = float(k[-1][4])
                if prev_close:
                    momentum = (close - prev_close) / prev_close
            except Exception:
                momentum = 0.0
        score = change + momentum * 100 + vol / 1_000_000
        ranked.append((score, symbol))
    ranked.sort(reverse=True)
    return [sym for _score, sym in ranked]


def detect_new_listings(
    prev: Dict[str, List[Dict[str, str]]],
    curr: Dict[str, List[Dict[str, str]]],
) -> List[str]:
    """Return list of new TRADING symbols between two ``exchangeInfo`` snapshots."""
    prev_syms = {s.get("symbol") for s in prev.get("symbols", [])}
    new_syms = []
    for s in curr.get("symbols", []):
        if s.get("status") == "TRADING" and s.get("symbol") not in prev_syms:
            new_syms.append(s.get("symbol"))
    return new_syms
