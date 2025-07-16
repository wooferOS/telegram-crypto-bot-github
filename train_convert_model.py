import json
import os
import sys
from typing import Any, Dict, List

import pandas as pd
from convert_logger import logger
from convert_model import (
    prepare_dataset,
    extract_features,
    extract_labels,
    train_model,
    save_model,
)

MODEL_PATH = "model_convert.joblib"
HISTORY_PATH = "logs/convert_history.json"


def load_convert_history(path: str = "convert_history.json") -> List[Dict[str, Any]]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"❌ Помилка при завантаженні історії: {e}")
        return []

def main():
    history = load_convert_history(HISTORY_PATH)
    if not history:
        logger.warning("⛔️ Історія порожня або недоступна.")
        return

    prepared = prepare_dataset(history)
    if not prepared:
        logger.error("❌ Немає даних після фільтрації prepare_dataset.")
        return

    X = extract_features(prepared)
    if X.shape[1] == 0 or X.size == 0:
        logger.error(
            "[dev3] ❌ Навчання зупинено: неможливо згенерувати ознаки — масив features порожній."
        )
        sys.exit(1)

    y = extract_labels(prepared)

    if len(y) == 0:
        logger.warning("⚠️ Немає міток для навчання.")
        return

    model = train_model(X, y)
    save_model(model, MODEL_PATH)

if __name__ == "__main__":
    main()
