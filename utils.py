import statistics
from typing import List, Dict, Optional

from binance_api import (
    get_usdt_to_uah_rate,
    get_price_history_24h,
)


def convert_to_uah(amount_usdt: float) -> float:
    """Convert amount in USDT to UAH."""
    return round(amount_usdt * get_usdt_to_uah_rate(), 2)


def calculate_rr(klines: List[List[float]]) -> float:
    """Return simple risk/reward ratio based on last 20 candles."""
    if not klines:
        return 0.0
    closes = [float(k[4]) for k in klines]
    lows = [float(k[3]) for k in klines]
    highs = [float(k[2]) for k in klines]
    last_close = closes[-1]
    support = min(lows[-20:])
    resistance = max(highs[-20:])
    risk = last_close - support
    reward = resistance - last_close
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def _ema(values: List[float], period: int) -> List[float]:
    """Calculate Exponential Moving Average."""
    k = 2 / (period + 1)
    ema = [statistics.fmean(values[:period])]
    for price in values[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema


def calculate_indicators(klines: List[List[float]]) -> Dict[str, float]:
    """Calculate basic indicators for token."""
    closes = [float(k[4]) for k in klines]

    ema5 = _ema(closes, 5)[-1] if closes else 0.0
    ema8 = _ema(closes, 8)[-1] if closes else 0.0
    ema13 = _ema(closes, 13)[-1] if closes else 0.0

    if len(closes) < 26:
        return {
            "RSI": 50.0,
            "MACD": "neutral",
            "support": closes[-1] if closes else 0.0,
            "resistance": closes[-1] if closes else 0.0,
            "EMA_5": ema5,
            "EMA_8": ema8,
            "EMA_13": ema13,
        }

    # RSI
    gains = []
    losses = []
    for i in range(1, 15):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(-diff)
    avg_gain = sum(gains) / 14 if gains else 0
    avg_loss = sum(losses) / 14 if losses else 0
    rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss else 100.0

    # MACD
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_val = ema12[-1] - ema26[-1]
    macd = "bullish" if macd_val >= 0 else "bearish"

    support = min(float(k[3]) for k in klines[-20:])
    resistance = max(float(k[2]) for k in klines[-20:])

    return {
        "RSI": rsi,
        "MACD": macd,
        "support": support,
        "resistance": resistance,
        "EMA_5": ema5,
        "EMA_8": ema8,
        "EMA_13": ema13,
    }


def get_sector(symbol: str) -> str:
    """Return sector for given symbol (placeholder)."""
    return "unknown"


def analyze_btc_correlation(symbol: str) -> float:
    """Return correlation of token prices with BTC scaled to 0..1."""
    token_prices = get_price_history_24h(symbol)
    btc_prices = get_price_history_24h("BTC")
    if not token_prices or not btc_prices:
        return 0.0
    min_len = min(len(token_prices), len(btc_prices))
    if min_len < 2:
        return 0.0
    token = token_prices[-min_len:]
    btc = btc_prices[-min_len:]
    try:
        corr = statistics.correlation(token, btc)
    except Exception:
        return 0.0
    result = (corr + 1) / 2
    return max(0.0, min(1.0, float(result)))
