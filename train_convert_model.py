import json
import logging
import os

from joblib import dump
import numpy as np
from sklearn.ensemble import RandomForestClassifier

from convert_logger import logger
from convert_model import MODEL_PATH

HISTORY_FILE = os.path.join("logs", "convert_history.json")
LOG_FILE = os.path.join("logs", "model_training.log")

logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(file_handler)


def extract_features(record):
    return [
        record.get("expected_profit", 0),
        record.get("prob_up", 0),
        record.get("score", 0),
        record.get("volatility", 0),
    ]


def main() -> None:
    if not os.path.exists(HISTORY_FILE):
        logger.warning("[dev3] convert_history.json not found")
        return

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception as exc:
        logger.warning("[dev3] failed to read history: %s", exc)
        return

    records = [rec for rec in history if rec.get("expected_profit") is not None]

    if not records or len(records) < 2:
        logger.warning("[dev3] Not enough data for training")
        return

    X = np.array([extract_features(rec) for rec in records], dtype=float)
    y = np.array([1 if rec.get("profit", 0) > 0 else 0 for rec in records], dtype=int)

    if X.shape[1] == 0:
        logger.error("[dev3] ❌ Порожній масив ознак для навчання")
        return

    model = RandomForestClassifier(n_estimators=50, random_state=42)
    model.fit(X, y)
    dump(model, MODEL_PATH)

    logger.info("[dev3] ✅ Модель навчено на %s записах", len(records))


if __name__ == "__main__":
    main()
