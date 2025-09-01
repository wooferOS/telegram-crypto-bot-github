import logging
import os

from joblib import dump
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from convert_logger import logger
from convert_model import MODEL_PATH, prepare_dataset

HISTORY_FILE = os.path.join("logs", "convert_history.json")
LOG_FILE = os.path.join("logs", "model_training.log")

logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(file_handler)

log = logger.info


def train_model(accepted: pd.DataFrame, rejected: pd.DataFrame) -> None:
    """Train RandomForest model on accepted/rejected trades."""
    df = pd.concat([accepted, rejected], ignore_index=True)
    X = df[["expected_profit", "prob_up", "score", "ratio", "inverseRatio"]]
    y = df["accepted"].astype(bool)

    model = RandomForestClassifier(n_estimators=50, random_state=42)
    model.fit(X, y)
    dump(model, MODEL_PATH)

    logger.info(
        f"✅ Навчання завершено: {len(df)} записів | accepted: {len(accepted)} | rejected: {len(rejected)}",
    )


def main():
    """Load history and train model if enough data is available."""
    try:
        df = pd.read_json(HISTORY_FILE, orient="records")
    except (ValueError, FileNotFoundError) as exc:
        logger.warning(
            f"[dev3] ❌ Історія недоступна {HISTORY_FILE}: {exc}",
        )
        return

    if df.empty or "accepted" not in df.columns:
        logger.warning(
            f"[dev3] ❌ Недостатньо даних для навчання у {HISTORY_FILE}",
        )
        return

    df["accepted"] = df["accepted"].astype(bool)
    accepted = df[df["accepted"]]
    rejected = df[~df["accepted"]]

    if accepted.empty or rejected.empty:
        logger.warning(
            f"❌ Недостатньо даних для навчання: accepted = {len(accepted)}, rejected = {len(rejected)}",
        )
        return

    train_model(accepted, rejected)


if __name__ == "__main__":
    main()
