import pandas as pd
import numpy as np
from typing import Dict
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score
from sklearn.base import BaseEstimator
from ml_model import load_model


def predict_proba(symbol: str, indicators: Dict[str, float]) -> float:
    """Return probability of successful growth using ML model."""
    model = load_model()
    if not model:
        return 0.5
    try:
        df = pd.DataFrame([indicators])
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(df)[0][1]
            return float(proba)
        pred = model.predict(df)[0]
        return 1.0 if int(pred) == 1 else 0.0
    except Exception:
        return 0.5


def walk_forward_validate(model: BaseEstimator, data: pd.DataFrame) -> Dict[str, float]:
    """Return best parameters via simple walk-forward validation."""
    tscv = TimeSeriesSplit(n_splits=3)
    best_score = -1.0
    best_params: Dict[str, float] = {}
    params_grid = [
        {"n_estimators": 100},
        {"n_estimators": 200},
    ]
    for params in params_grid:
        try:
            model.set_params(**params)
        except Exception:
            continue
        scores = []
        for train_idx, test_idx in tscv.split(data):
            X_train = data.iloc[train_idx].drop(columns=["target"], errors="ignore")
            y_train = data.iloc[train_idx]["target"]
            X_test = data.iloc[test_idx].drop(columns=["target"], errors="ignore")
            y_test = data.iloc[test_idx]["target"]
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
            scores.append(accuracy_score(y_test, pred))
        mean_score = float(np.mean(scores))
        if mean_score > best_score:
            best_score = mean_score
            best_params = params
    return best_params
