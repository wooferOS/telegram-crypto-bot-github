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

    records = [rec for rec in history if rec.get("accepted")]
    if not records:
        logger.warning("[dev3] No executed conversions for training")
        return

    features = [rec.get("features", []) for rec in records]
    targets = [1 if rec.get("profit", 0) > 0 else 0 for rec in records]

    if len(records) < 2:
        logger.warning("[dev3] Not enough data for training")
        return

    X = np.array(features, dtype=float)
    y = np.array(targets, dtype=int)

    model = RandomForestClassifier(n_estimators=50, random_state=42)
    model.fit(X, y)
    dump(model, MODEL_PATH)

    logger.info("[dev3] \u2705 Модель навчено на %s записах", len(records))


if __name__ == "__main__":
    main()
