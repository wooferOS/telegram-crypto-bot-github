import json
import os
import sys
from typing import Any, Dict, List
from datetime import datetime, timezone
import logging
from collections import Counter
import argparse

import joblib

logging.basicConfig(
    filename="logs/train_model.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)

import pandas as pd
from convert_logger import logger

# Ensure the latest convert_model is loaded
import importlib
import convert_model as _convert_model
importlib.reload(_convert_model)
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force-train", action="store_true", help="Allow training even with one class"
    )
    parser.add_argument(
        "--debug-data",
        action="store_true",
        help="Save prepared dataset to logs/debug_train.csv",
    )
    args = parser.parse_args()
    try:
        history = load_convert_history(HISTORY_PATH)
        if not history:
            logger.warning("⛔️ Історія порожня або недоступна.")
            return

        prepared = prepare_dataset(history)
        for row in prepared:
            amount_data = row.get("amount", 0.0)
            if isinstance(amount_data, dict):
                row["amount"] = float(amount_data.get("from", 0.0))
            else:
                row["amount"] = float(amount_data)
        if not prepared:
            logger.error("❌ Немає даних після фільтрації prepare_dataset.")
            return
        if len(prepared) < 20:
            logger.warning(
                f"[dev3] 🚫 Недостатньо даних для навчання: {len(prepared)}"
            )
            return

        df = pd.DataFrame(prepared)
        if args.debug_data:
            os.makedirs("logs", exist_ok=True)
            df.to_csv("logs/debug_train.csv", index=False)

        class_counts = Counter(df["executed"])
        if len(class_counts) == 1 and False in class_counts:
            logger.warning(
                "[dev3] ⚠️ Model trained on one class only — ефективність буде обмеженою"
            )
        if len(class_counts) < 2:
            if not args.force_train:
                print(
                    f"[FATAL] ❌ Training aborted: only one class present — {class_counts}"
                )
                sys.exit(1)
            else:
                print(
                    f"[WARNING] ⚠️ Training on one class only — {class_counts} (forced)"
                )
        else:
            print(f"[OK] ✅ Training dataset class distribution: {class_counts}")

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
        logger.info(
            "[dev3] executed=True=%d executed=False=%d",
            class_counts.get(True, 0),
            class_counts.get(False, 0),
        )
        print(
            "[dev3] ✅ Model trained (forced mode)"
            if args.force_train
            else "[dev3] ✅ Model trained successfully"
        )
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
