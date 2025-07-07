import json
import logging
import os

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor

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
        logger.info("No history found")
        return
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ✅ Фільтруємо лише записи з явним accepted: true або false
    data = [item for item in data if item.get("accepted") in [True, False]]

    if not data:
        print("❌ Недостатньо даних для навчання: accepted == True/False відсутні.")
        return

    X = np.array([
        [item.get("score", 0.0), item.get("ratio", 0.0), item.get("inverseRatio", 0.0)]
        for item in data
    ])
    y = np.array([item["accepted"] for item in data])

    print(
        f"✅ Навчання на {len(X)} прикладах ({sum(y)} позитивних, {len(y)-sum(y)} негативних)"
    )

    model = RandomForestRegressor(n_estimators=50)
    model.fit(X, y)
    joblib.dump(model, MODEL_PATH)
    logger.info("Model trained on %d records", len(data))


if __name__ == "__main__":
    main()
