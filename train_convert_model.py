import json
import os
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import joblib
from convert_logger import logger

MODEL_PATH = "model_convert.joblib"
HISTORY_PATH = "logs/convert_history.json"

def extract_features(data):
    feature_keys = ["expected_profit", "prob_up", "score", "volatility"]
    df = pd.DataFrame([
        {k: float(trade.get(k, 0)) for k in feature_keys}
        for trade in data
    ])
    return df

def extract_labels(data):
    return [1 if trade.get("accepted") else 0 for trade in data]

def load_history(path):
    if not os.path.exists(path):
        logger.warning(f"❌ Файл історії не знайдено: {path}")
        return []
    with open(path, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"⚠️ Неможливо прочитати JSON: {path}")
            return []

def main():
    history = load_history(HISTORY_PATH)
    if not history:
        logger.warning("⛔️ Історія порожня або недоступна.")
        return

    X = extract_features(history)
    y = extract_labels(history)

    if X.shape[1] == 0 or len(y) == 0:
        logger.warning("⚠️ Немає ознак або міток для навчання.")
        return

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X, y)

    joblib.dump(model, MODEL_PATH)
    logger.info(f"✅ Модель збережено в {MODEL_PATH}")

if __name__ == "__main__":
    main()
