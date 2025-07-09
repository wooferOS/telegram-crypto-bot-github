import json
import logging
import os

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor

from convert_logger import logger
from convert_model import MODEL_PATH, prepare_dataset

HISTORY_FILE = os.path.join("logs", "convert_history.json")
LOG_FILE = os.path.join("logs", "model_training.log")


logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(file_handler)


def main() -> None:
    PREDICTIONS_FILE = os.path.join("logs", "predictions.json")

    if not os.path.exists(PREDICTIONS_FILE):
        logger.warning("[dev3] ❌ Відсутній файл predictions.json — навчання пропущено.")
        return

    with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
        try:
            predictions_data = json.load(f)
            if not predictions_data:
                logger.warning("[dev3] ⚠️ Порожній файл predictions.json — навчання пропущено.")
                return
        except json.JSONDecodeError:
            logger.warning("[dev3] ❌ Неможливо зчитати predictions.json — файл пошкоджений.")
            return
    if not os.path.exists(HISTORY_FILE):
        logger.info("No history found")
        return
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)

    # ✅ Фільтруємо лише записи з явним accepted: true або false
    history = [item for item in history if item.get("accepted") in [True, False]]
    dataset = prepare_dataset(history)

    # Використовуємо лише останні 500 прикладів
    dataset = dataset[-500:]

    has_true = any(x.get("accepted") is True for x in dataset)
    has_false = any(x.get("accepted") is False for x in dataset)

    if not has_true and not has_false:
        logger.warning("[dev3] ❌ Недостатньо даних для навчання: accepted == True/False відсутні.")
        return

    logger.info(
        f"[dev3] 🔁 accepted=True: {sum(1 for x in dataset if x.get('accepted') is True)}, accepted=False: {sum(1 for x in dataset if x.get('accepted') is False)}"
    )

    X_train = np.array([
        [item.get("score", 0.0), item.get("ratio", 0.0), item.get("inverseRatio", 0.0)]
        for item in dataset
    ])
    y = np.array([item["accepted"] for item in dataset])

    logger.info(
        f"[dev3] ✅ Навчання на {len(X_train)} прикладах ({sum(y)} позитивних, {len(y)-sum(y)} негативних)"
    )

    model = RandomForestRegressor(n_estimators=50)
    model.fit(X_train, y)
    joblib.dump(model, MODEL_PATH)
    logger.info("Model trained on %d records", len(history))
    logger.info(f"[dev3] ℹ️ Feature importance: {model.feature_importances_}")
    logger.info(f"[dev3] Модель навчена на {len(X_train)} прикладах")


if __name__ == "__main__":
    main()
