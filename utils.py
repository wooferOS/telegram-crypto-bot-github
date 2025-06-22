import logging
import statistics
import os
import datetime
from typing import List, Dict, TYPE_CHECKING

if TYPE_CHECKING:  # Avoid circular import at runtime
    from binance_api import (
        get_usdt_to_uah_rate,
        get_price_history_24h,
        get_symbol_price,
        get_klines_safe as get_klines,
    )

logger = logging.getLogger(__name__)


def convert_to_uah(amount_usdt: float) -> float:
    """Convert amount in USDT to UAH."""
    from binance_api import get_usdt_to_uah_rate

    return round(amount_usdt * get_usdt_to_uah_rate(), 2)


def adjust_qty_to_step(qty: float, step: float, min_qty: float = 0.0) -> float:
    """Round ``qty`` down to comply with ``step`` size taking ``min_qty`` into account."""

    from decimal import Decimal, ROUND_DOWN, getcontext

    getcontext().prec = 18
    d_qty = Decimal(str(qty))
    d_step = Decimal(str(step))
    d_min = Decimal(str(min_qty))
    if d_step == 0:
        return float(d_qty)
    adjusted = ((d_qty - d_min) // d_step) * d_step + d_min
    return float(adjusted.quantize(d_step, rounding=ROUND_DOWN))


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


def dynamic_tp_sl(closes: List[float], price: float) -> tuple[float, float]:
    """Return take profit and stop loss levels based on recent volatility."""
    if len(closes) < 10:
        return round(price * 1.1, 6), round(price * 0.95, 6)
    volatility = statistics.pstdev(closes[-10:])
    avg_price = statistics.mean(closes[-10:])
    factor = volatility / avg_price if avg_price else 0

    tp = round(price * (1 + min(0.15, 2.0 * factor)), 6)
    sl = round(price * (1 - max(0.03, 0.5 * factor)), 6)
    return tp, sl


def estimate_profit_debug(symbol: str) -> float:
    try:
        from binance_api import get_symbol_price, get_klines_safe as get_klines

        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        price = get_symbol_price(pair)
        if price is None or price <= 0:
            logger.warning("estimate_profit: no price for %s", pair)
            return 0.0

        klines = get_klines(pair)
        if not klines:
            logger.warning("estimate_profit: no klines for %s", pair)
            return 0.0

        closes = [float(k[4]) for k in klines]
        tp_price, sl_price = dynamic_tp_sl(closes, price)

        expected_profit = calculate_expected_profit(
            price=price,
            tp_price=tp_price,
            amount=10,
            sl_price=sl_price,
            success_rate=0.75,
            fee=0.001,
        )
        logger.info(
            "🧮 %s: price=%s, tp=%s, sl=%s, exp=%s",
            symbol,
            price,
            tp_price,
            sl_price,
            expected_profit,
        )
        return expected_profit
    except Exception as e:
        logger.warning(f"⚠️ get_klines failed for {symbol}: {e}")
        logger.error("estimate_profit error for %s: %s", symbol, e)
        return 0.0


def calculate_indicators(klines: List[List[float]]) -> Dict[str, float]:
    """Calculate trading indicators used for filtering."""
    if not klines or not isinstance(klines[0], (list, tuple)):
        raise TypeError(
            f"❌ Неправильний формат klines: {type(klines[0])}, очікується список OHLCV"
        )

    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]

    ema8 = _ema(closes, 8)[-1] if closes else 0.0
    ema13 = _ema(closes, 13)[-1] if closes else 0.0
    momentum = ema8 - ema13

    rsi = _ema(closes, 14)[-1] if len(closes) >= 14 else closes[-1] if closes else 0.0

    mid = statistics.mean(closes[-20:]) if len(closes) >= 20 else statistics.mean(closes) if closes else 0.0
    stddev = statistics.pstdev(closes[-20:]) if len(closes) >= 20 else 0.0
    lower = mid - 2 * stddev
    bb_touch = closes[-1] <= lower if closes else False

    macd_line = _ema(closes, 12)[-1] - _ema(closes, 26)[-1] if len(closes) >= 26 else 0.0
    signal_line = _ema(closes, 9)[-1] if len(closes) >= 9 else 0.0
    macd_cross = macd_line > signal_line and macd_line - signal_line > 0

    support = min(lows[-20:]) if len(lows) >= 20 else min(lows) if lows else 0.0
    resistance = max(highs[-20:]) if len(highs) >= 20 else max(highs) if highs else 0.0

    return {
        "RSI": rsi,
        "EMA_8": ema8,
        "EMA_13": ema13,
        "momentum": momentum,
        "MACD_CROSS": macd_cross,
        "BB_LOWER_TOUCH": bb_touch,
        "support": support,
        "resistance": resistance,
    }


def get_sector(symbol: str) -> str:
    """Return sector for given symbol (placeholder)."""
    return "unknown"


def analyze_btc_correlation(symbol: str) -> float:
    """Return correlation of token prices with BTC scaled to 0..1."""
    from binance_api import get_price_history_24h

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


def get_risk_reward_ratio(price: float, stop_loss: float, take_profit: float) -> float:
    """
    Розрахунок співвідношення ризик/нагорода (Risk/Reward)
    """
    risk = price - stop_loss
    reward = take_profit - price
    if risk <= 0:
        return 0
    return round(reward / risk, 2)


def get_correlation_with_btc(asset_closes: list, btc_closes: list) -> float:
    """
    Розрахунок кореляції токена з BTC за списками цін
    """
    if len(asset_closes) != len(btc_closes) or len(asset_closes) == 0:
        return 1.0  # Максимальна кореляція за замовчуванням
    mean_asset = sum(asset_closes) / len(asset_closes)
    mean_btc = sum(btc_closes) / len(btc_closes)
    numerator = sum((a - mean_asset) * (b - mean_btc) for a, b in zip(asset_closes, btc_closes))
    denominator = (sum((a - mean_asset) ** 2 for a in asset_closes) * sum((b - mean_btc) ** 2 for b in btc_closes)) ** 0.5
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 2)


def kelly_fraction(success_rate: float, win_loss_ratio: float) -> float:
    """Return position size fraction using Kelly formula."""
    return max(0.01, min(0.25, (success_rate * (win_loss_ratio + 1) - 1) / win_loss_ratio))

def calculate_expected_profit(
    price: float,
    tp_price: float,
    amount: float,
    sl_price: float | None = None,
    success_rate: float = 0.75,
    fee: float = 0.001,
) -> float:
    """Return expected profit adjusted for fees and risk."""

    if price <= 0 or tp_price <= price:
        return 0.0

    gross = (tp_price - price) / price * amount
    loss = ((price - sl_price) / price * amount) if sl_price and sl_price < price else 0

    net_profit = gross * (1 - 2 * fee)
    expected = net_profit * success_rate - loss * (1 - success_rate)
    return round(expected, 4)


def advanced_buy_filter(token: dict) -> bool:
    """Return True if token passes advanced technical filters."""

    indicators = token.get("indicators", {})
    rsi = indicators.get("RSI", 50)
    macd_cross = indicators.get("MACD_CROSS", False)
    bb_touch = indicators.get("BB_LOWER_TOUCH", False)
    momentum = token.get("momentum", 0)
    rr = token.get("risk_reward", 0)

    return (
        rsi < 40
        and macd_cross
        and bb_touch
        and momentum > 0
        and rr > 1.5
    )


def log_trade(action: str, symbol: str, qty: float, price: float) -> None:
    """Append trade information to ``logs/trade.log``."""

    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} {action} {symbol} qty={qty} price={price}\n"
    with open("logs/trade.log", "a", encoding="utf-8") as log_file:
        log_file.write(line)


