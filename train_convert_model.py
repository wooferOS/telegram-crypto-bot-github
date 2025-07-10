import json
import logging
import os

from joblib import dump
import numpy as np
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


def main():
    df = pd.read_json("convert_history.json", orient="records")
    print("[DEBUG] df shape:", df.shape)
    print("[DEBUG] df columns:", df.columns.tolist())
    print("[DEBUG] accepted column unique values:", df["accepted"].unique())
    print("[DEBUG] accepted value_counts:\n", df["accepted"].value_counts())

    accepted = df[df["accepted"] == True]
    rejected = df[df["accepted"] == False]

    print("[DEBUG] accepted sample:\n", accepted.head())
    print("[DEBUG] rejected sample:\n", rejected.head())

    df["accepted"] = df["accepted"].astype(bool)
    log(f"[DEBUG] Колонки: {df.columns.tolist()}")
    log(f"[DEBUG] Перші рядки:\n{df.head()}")

    if "accepted" not in df.columns:
        log("❌ Колонка 'accepted' відсутня у convert_history.json. Навчання неможливе.")
        return

    accepted = df[df["accepted"]]
    rejected = df[~df["accepted"]]

    if accepted.empty or rejected.empty:
        log("❌ Недостатньо даних для навчання: accepted == True/False відсутні.")
        return

    X = df[["expected_profit", "prob_up", "score", "ratio", "inverseRatio"]]
    y = df["accepted"]

    model = RandomForestClassifier(n_estimators=50, random_state=42)
    model.fit(X, y)
    dump(model, "model_convert.joblib")

    log(
        f"✅ Навчання завершено: {len(df)} записів | accepted: {len(accepted)} | rejected: {len(rejected)}"
    )


if __name__ == "__main__":
    main()
