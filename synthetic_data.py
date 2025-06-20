import pandas as pd
import numpy as np


def generate_scenarios(data: pd.DataFrame) -> pd.DataFrame:
    """Add noise or crisis patterns to historical data."""
    noisy = data.copy()
    if "close" in noisy:
        noise = np.random.normal(0, noisy["close"].std() * 0.01, size=len(noisy))
        noisy["close"] = noisy["close"] + noise
    # simple crisis pattern
    if len(noisy) > 10:
        idx = np.random.randint(0, len(noisy) - 10)
        noisy.loc[idx : idx + 5, "close"] *= 0.7
    return noisy
