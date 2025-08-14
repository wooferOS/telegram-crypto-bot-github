import logging
import os
from typing import Any, Tuple, List, Dict
import hashlib

import numpy as np

import joblib
import pandas as pd
from utils_dev3 import safe_float
from run_convert_trade import load_top_pairs

MODEL_PATH = "model_convert.joblib"
logger = logging.getLogger(__name__)
_model = None
_is_fallback = False
_model_valid = False




def train_model(X, y):
    from sklearn.ensemble import RandomForestClassifier

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X, y)
    logger.info("[dev3] \U0001f3af Навчання завершено: %d записів", len(y))
    return model


def save_model(model, path=MODEL_PATH):
    joblib.dump(model, path)
    logger.info("[dev3] \U0001f4be Модель збережено у %s", path)


def prepare_dataset(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return dataset for training including executed flag."""
    if not history:
        return []

    df = pd.DataFrame(history)

    # Фільтруємо записи без expected_profit
    if "expected_profit" in df.columns:
        df = df[df["expected_profit"].notnull()]

    if "accepted" in df.columns:
        df["executed"] = df["accepted"].fillna(False).astype(bool)
    elif "success" in df.columns:
        df["executed"] = df["success"].fillna(False).astype(bool)
    else:
        df["executed"] = False

    return df.to_dict("records")

def extract_labels(data: List[Dict[str, Any]]) -> List[int]:
    return [1 if trade.get("accepted") or trade.get("success") else 0 for trade in data]


def _load_model() -> Any:
    """Load model from disk or return cached instance."""
    global _model, _is_fallback, _model_valid
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            _model_valid = False
            raise FileNotFoundError(MODEL_PATH)
        try:
            _model = joblib.load(MODEL_PATH)
            _model_valid = True
            if hasattr(_model, "classes_") and len(_model.classes_) == 1:
                _is_fallback = True
                print("[dev3] ⚠️ Model has one class — limited accuracy")
            else:
                _is_fallback = False
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.warning("Failed to load model: %s", exc)
            _model = None
            _is_fallback = False
            _model_valid = False
    return _model


def is_fallback_model() -> bool:
    """Return True if the currently loaded model is fallback."""
    global _model, _is_fallback
    if _model is None:
        try:
            _load_model()
        except FileNotFoundError:
            return False
    return _is_fallback


def model_is_valid() -> bool:
    """Return True if a trained model is available and valid."""
    global _model_valid
    return _model_valid


def _hash_token(token: str) -> float:
    """Convert token symbol to a normalized numeric hash."""
    return float(int(hashlib.sha256(token.encode()).hexdigest(), 16) % 10**8) / 1e8


def extract_features(history: List[Dict[str, Any]]) -> np.ndarray:
    """Build feature matrix from dataset for training."""
    features_list = []
    for row in history:
        ratio_value = row.get("ratio")
        if ratio_value is None:
            logger.warning("[dev3] ratio is None in history row: %s", row)
        ratio = safe_float(ratio_value)

        inverse_ratio_value = row.get("inverseRatio")
        if inverse_ratio_value is None:
            logger.warning("[dev3] inverseRatio is None in history row: %s", row)
        inverse_ratio = safe_float(inverse_ratio_value)

        expected_profit_val = row.get("expected_profit")
        if expected_profit_val is None:
            logger.warning("[dev3] expected_profit is None in history row: %s", row)

        prob_up_val = row.get("prob_up")
        if prob_up_val is None:
            logger.warning("[dev3] prob_up is None in history row: %s", row)

        score_val = safe_float(row.get("score"))
        if score_val is None:
            logger.warning("[dev3] score is None in history row: %s", row)

        amount = safe_float(row.get("amount"))
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


def predict(
    from_token: str, to_token: str, quote_data: dict
) -> Tuple[float, float, float]:
    """Return (expected_profit, probability_up, score) using trained model."""
    logger.debug(
        "[dev3] predict input from=%s to=%s data=%s", from_token, to_token, quote_data
    )
    try:
        model = _load_model()
    except FileNotFoundError:
        logger.debug("[dev3] model file not found")
        _model_valid = False
        return 0.0, 0.0, 0.0

    if model is None:
        _model_valid = False
        return 0.0, 0.0, 0.0

    try:
        ratio = safe_float(quote_data.get("ratio", 0.0))
        inverse_ratio = safe_float(quote_data.get("inverseRatio", 0.0))
        amount = safe_float(quote_data.get("amount", {}).get("from", 0.0))

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
            probas = model.predict_proba(features)[0]
            if len(probas) == 2:
                prob_up = float(probas[1])
            elif model.classes_[0] == 1:
                prob_up = float(probas[0])
            else:
                prob_up = 0.0
                logger.warning(
                    "[dev3] \u26A0\uFE0F Model has only one class: %s — prediction may be biased",
                    model.classes_,
                )
                logger.warning(
                    "[dev3] \U0001f916 Model prediction fallback: prob_up=%.3f",
                    prob_up,
                )
        else:
            prob_up = float(model.predict(features)[0])

        expected_profit = ratio - 1.0
        score_val = expected_profit * prob_up
        if expected_profit <= -0.999 and abs(prob_up - 0.57) < 0.01:
            logger.warning("[dev3] invalid model prediction sentinel detected")
            _model_valid = False
            return 0.0, 0.0, 0.0

        logger.debug(
            "[dev3] predict result: expected_profit=%.6f prob_up=%.6f score=%.6f",
            expected_profit,
            prob_up,
            score_val,
        )
        return expected_profit, prob_up, score_val
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.exception("[dev3] prediction failed: %s", exc)
        _model_valid = False
        return 0.0, 0.0, 0.0


def get_top_token_pairs(n: int = 5) -> List[Tuple[str, str]]:
    """Return top token pairs from top_tokens.json."""
    data = load_top_pairs("top_tokens.json")
    pairs: List[Tuple[str, str]] = []
    for item in data:
        from_token = item.get("from")
        to_token = item.get("to")
        if from_token and to_token:
            pairs.append((from_token, to_token))
        if len(pairs) >= n:
            break
    return pairs


def load_pairs_for_training(path: str = "top_tokens.json") -> List[Dict[str, Any]]:
    pairs = load_top_pairs(path)
    if len(pairs) < 20:
        logger.warning("🚫 Недостатньо даних для навчання: %d", len(pairs))
        return []
    return pairs
