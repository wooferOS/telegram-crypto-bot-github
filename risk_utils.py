from typing import List


def calculate_risk_reward(prob_up: float, expected_profit: float) -> float:
    """Return risk/reward ratio based on ``prob_up`` and ``expected_profit``."""
    expected_loss = (1 - prob_up) * abs(expected_profit)
    if expected_loss <= 0:
        return 0.0
    return round(expected_profit / expected_loss, 2)


def max_drawdown(returns: List[float]) -> float:
    """Return maximum drawdown for a series of returns."""
    if not returns:
        return 0.0
    peak = returns[0]
    trough = returns[0]
    max_dd = 0.0
    cumulative = 0.0
    for r in returns:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
            trough = cumulative
        if cumulative < trough:
            trough = cumulative
            dd = (peak - trough) / max(1e-8, abs(peak))
            max_dd = max(max_dd, dd)
    return round(max_dd, 4)
