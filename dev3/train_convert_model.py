import json
import logging
import os

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from convert_logger import logger
from convert_model import MODEL_PATH

HISTORY_FILE = "convert_history.json"
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
    if not data:
        logger.info("Empty history")
        return
    df = pd.DataFrame(data)
    if df.empty:
        logger.info("No data for training")
        return
    X = pd.get_dummies(df[["from", "to"]])
    X["amount"] = df.get("amount", 0)
    y = df.get("result", 0)
    model = RandomForestRegressor(n_estimators=50)
    model.fit(X, y)
    joblib.dump(model, MODEL_PATH)
    logger.info("Model trained on %d records", len(df))


if __name__ == "__main__":
    main()
