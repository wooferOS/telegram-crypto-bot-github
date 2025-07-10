import json
import logging
import os

import joblib
import numpy as np
import pandas as pd
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
    logger.info("[dev3] ▶️ Старт навчання моделі convert_model на основі convert_history.json")
    if not os.path.exists(HISTORY_FILE):
        logger.info("[dev3] ❌ convert_history.json відсутній")
        return
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)

    # ✅ Фільтруємо лише записи з явним accepted: true або false
    history = [item for item in history if item.get("accepted") in [True, False]]
    dataset = prepare_dataset(history)

    # Використовуємо лише останні 500 прикладів
    dataset = dataset[-500:]

    df = pd.DataFrame(dataset)

    print("[DEBUG] df.columns:", df.columns.tolist())
    print("[DEBUG] df head:\n", df.head())

    accepted = df[df["accepted"] == True]
    rejected = df[df["accepted"] == False]

    if len(accepted) == 0 or len(rejected) == 0:
        logger.warning(
            "❌ Замало прикладів для навчання: accepted = %s, rejected = %s",
            len(accepted),
            len(rejected),
        )
    else:
        logger.info(
            "✅ Початок навчання: accepted = %s, rejected = %s",
            len(accepted),
            len(rejected),
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
    logger.info(f"[dev3] Model trained on {len(history)} records")
    logger.info(f"[dev3] ℹ️ Feature importance: {model.feature_importances_}")
    logger.info(f"[dev3] Модель навчена на {len(X_train)} прикладах")


if __name__ == "__main__":
    main()
