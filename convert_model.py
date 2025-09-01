import logging
import os
from typing import Any, Tuple, List, Dict
import hashlib

import numpy as np

import joblib

MODEL_PATH = "model_convert.joblib"
logger = logging.getLogger(__name__)
_model = None


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
    return float(int(hashlib.sha256(token.encode()).hexdigest(), 16) % 10**8)


def predict(from_token: str, to_token: str, quote_data: dict) -> Tuple[float, float, float]:
    """Return (expected_profit, probability_up, score) using trained model."""
    logger.debug(
        "[dev3] predict input from=%s to=%s data=%s", from_token, to_token, quote_data
    )
    def _fallback() -> Tuple[float, float, float]:
        ratio = float(quote_data.get("ratio", 1.0))
        expected_profit = float(quote_data.get("expected_profit", ratio - 1.0))
        prob_up = float(quote_data.get("prob_up", 0.5))
        score = expected_profit * prob_up
        logger.debug("[dev3] fallback prediction used")
        return expected_profit, prob_up, score

    try:
        model = _load_model()
    except FileNotFoundError:
        logger.debug("[dev3] model file not found")
        return _fallback()

    if model is None:
        return _fallback()

    try:
        ratio = float(quote_data.get("ratio", 0.0))
        inverse_ratio = float(quote_data.get("inverseRatio", 0.0))

        expected_profit = float(quote_data.get("expected_profit", ratio - 1.0))
        prob_up = float(quote_data.get("prob_up", 0.5))
        score = float(quote_data.get("score", expected_profit * prob_up))

        features = np.array(
            [[expected_profit, prob_up, score, ratio, inverse_ratio]], dtype=float
        )
        norm = np.linalg.norm(features, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        features = features / norm

        if hasattr(model, "predict_proba"):
            prob_up = float(model.predict_proba(features)[0][1])
        else:
            prob_up = float(model.predict(features)[0])

        expected_profit = float(expected_profit)
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
        return _fallback()
