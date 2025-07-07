import logging
import os
from typing import Any, Tuple

import numpy as np

import joblib

MODEL_PATH = "model_convert.joblib"
logger = logging.getLogger(__name__)
_model = None


def _load_model():
    global _model
    if _model is None and os.path.exists(MODEL_PATH):
        try:
            _model = joblib.load(MODEL_PATH)
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.warning("Failed to load model: %s", exc)
            _model = None
    return _model


def predict(from_token: str, to_token: str, quote_data: dict) -> Tuple[float, float, float]:
    model = _load_model()
    if not model:
        return 0.0, 0.5, 0.0
    try:
        score = quote_data.get("score", 0.0)
        ratio = quote_data.get("ratio", 0.0)
        inverse_ratio = quote_data.get("inverseRatio", 0.0)
        features = np.array([[score, ratio, inverse_ratio]])
        if hasattr(model, "predict_proba"):
            prob = float(model.predict_proba(features)[0][1])
        else:
            prob = float(model.predict(features)[0])
        expected_profit = ratio * prob
        score = expected_profit * prob
        return expected_profit, prob, score
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.exception("prediction failed: %s", exc)
        return 0.0, 0.5, 0.0
