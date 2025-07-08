import numpy as np


def get_rsi(prices: list[float], period: int = 14) -> float:
    deltas = np.diff(prices)
    ups = np.where(deltas > 0, deltas, 0)
    downs = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(ups[-period:])
    avg_loss = np.mean(downs[-period:]) or 1e-9
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_macd(prices: list[float]) -> tuple[float, float]:
    ema12 = np.mean(prices[-12:])
    ema26 = np.mean(prices[-26:])
    macd_line = ema12 - ema26
    signal_line = np.mean([ema12 - ema26 for _ in range(9)])  # просте згладжування
    return macd_line, signal_line
