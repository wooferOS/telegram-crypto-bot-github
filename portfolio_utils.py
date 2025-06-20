from typing import Dict, List
import numpy as np
import pandas as pd


def hierarchical_risk_parity(candidates: List[dict]) -> Dict[str, float]:
    """Return allocation ratios based on Hierarchical Risk Parity."""
    if not candidates:
        return {}
    symbols = [c["symbol"] for c in candidates]
    try:
        data = {c["symbol"]: c.get("history", []) for c in candidates}
        df = pd.DataFrame(data)
        corr = df.corr().fillna(0)
        inv_var = 1 / np.diag(corr.values)
        weights = inv_var / inv_var.sum()
        return {sym: float(w) for sym, w in zip(symbols, weights)}
    except Exception:
        equal = 1 / len(candidates)
        return {sym: equal for sym in symbols}
