import logging
import os
from typing import Any, Tuple, List, Dict
import hashlib

import numpy as np

import joblib

MODEL_PATH = "model_convert.joblib"
logger = logging.getLogger(__name__)
_model = None


def train_model(X, y):
    from sklearn.ensemble import RandomForestClassifier
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X, y)
    logger.info("[dev3] \U0001F3AF Навчання завершено: %d записів", len(y))
    return model


def save_model(model, path=MODEL_PATH):
    joblib.dump(model, path)
    logger.info("[dev3] \U0001F4BE Модель збережено у %s", path)


def prepare_dataset(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter raw history into a dataset used for training."""
    return [x for x in history if x.get("score", 0) > 0 and x.get("expected_profit", 0) > 0]


def _load_model() -> Any:
    """Load model from disk or return cached instance."""
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(MODEL_PATH)
        try:
            _model = joblib.load(MODEL_PATH)
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.warning("Failed to load model: %s", exc)
            _model = None
    return _model


def _hash_token(token: str) -> float:
    """Convert token symbol to a normalized numeric hash."""
    return float(int(hashlib.sha256(token.encode()).hexdigest(), 16) % 10**8) / 1e8


def extract_features(history: List[Dict[str, Any]]) -> np.ndarray:
    """Build feature matrix from dataset for training."""
    features_list = []
    for row in history:
        ratio = float(row.get("ratio", 0.0))
        inverse_ratio = float(row.get("inverseRatio", 0.0))
        amount = float(row.get("amount", 0.0))
        from_hash = _hash_token(row.get("from_token", ""))
        to_hash = _hash_token(row.get("to_token", ""))
        features_list.append([ratio, inverse_ratio, amount, from_hash, to_hash])

    if not features_list:
        logging.warning(
            f"[dev3] ❗ features_list порожній — історія конверсій: {len(history)} записів"
        )
        return np.zeros((0, 5))

    features = np.array(features_list, dtype=float)
    norm = np.linalg.norm(features, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return features / norm


def predict(from_token: str, to_token: str, quote_data: dict) -> Tuple[float, float, float]:
    """Return (expected_profit, probability_up, score) using trained model."""
    logger.debug(
        "[dev3] predict input from=%s to=%s data=%s", from_token, to_token, quote_data
    )
    try:
        model = _load_model()
    except FileNotFoundError:
        logger.debug("[dev3] model file not found")
        return 0.0, 0.0, 0.0

    if model is None:
        return 0.0, 0.0, 0.0

    try:
        ratio = float(quote_data.get("ratio", 0.0))
        inverse_ratio = float(quote_data.get("inverseRatio", 0.0))
        amount = float(quote_data.get("amount", 0.0))

        features = np.array(
            [
                [
                    ratio,
                    inverse_ratio,
                    amount,
                    _hash_token(from_token),
                    _hash_token(to_token),
                ]
            ],
            dtype=float,
        )
        norm = np.linalg.norm(features, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        features = features / norm

        if hasattr(model, "predict_proba"):
            prob_up = float(model.predict_proba(features)[0][1])
        else:
            prob_up = float(model.predict(features)[0])

        expected_profit = ratio - 1.0
        score_val = expected_profit * prob_up

        logger.debug(
            "[dev3] predict result: expected_profit=%.6f prob_up=%.6f score=%.6f",
            expected_profit,
            prob_up,
            score_val,
        )
        return expected_profit, prob_up, score_val
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.exception("[dev3] prediction failed: %s", exc)
        return 0.0, 0.0, 0.0
