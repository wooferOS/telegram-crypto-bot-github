import json
import os
import sys
from typing import Any, Dict, List
from datetime import datetime, timezone
import logging
from collections import Counter

import joblib

logging.basicConfig(
    filename="logs/train_model.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)

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
    try:
        history = load_convert_history(HISTORY_PATH)
        if not history:
            logger.warning("⛔️ Історія порожня або недоступна.")
            return

        prepared = prepare_dataset(history)
        if not prepared:
            logger.error("❌ Немає даних після фільтрації prepare_dataset.")
            return
        if len(prepared) < 20:
            logger.warning(
                f"[dev3] 🚫 Недостатньо даних для навчання: {len(prepared)}"
            )
            return

        labels = [d["executed"] for d in prepared if "executed" in d]
        label_counts = Counter(labels)
        if len(label_counts) < 2:
            print(f"[FATAL] ❌ Training aborted: only one class present — {label_counts}")
            sys.exit(1)
        else:
            print(f"[OK] ✅ Training dataset class distribution: {label_counts}")

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

        if pd.Series(y).nunique() < 2:
            logger.error(
                "[dev3] \u274c Cannot train model \u2014 only one class (%s) in label column",
                pd.Series(y).unique(),
            )
            sys.exit(1)

        model = train_model(X, y)
        save_model(model, MODEL_PATH)
        print("[dev3] 🤖 Model saved successfully.")
        try:
            joblib.load(MODEL_PATH)
        except Exception as exc:
            logger.error(f"❌ Failed to load saved model: {exc}")
            sys.exit(1)


        logging.info(
            f"\u2705 \u041d\u0430\u0432\u0447\u0430\u043d\u043d\u044f \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e. \u0420\u044f\u0434\u043a\u0456\u0432 \u0443 \u0434\u0430\u0442\u0430\u0441\u0435\u0442\u0456: {len(X)}"
        )
    except Exception:
        logging.exception("❌ Помилка під час навчання моделі")


if __name__ == "__main__":
    main()
