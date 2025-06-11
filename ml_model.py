import joblib
import os
import numpy as np
from sklearn.svm import SVC
from sklearn.model_selection import train_test_split

MODEL_PATH = "svm_direction_model.pkl"


def prepare_dataset(token_klines: list[list[float]]) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for i in range(30, len(token_klines) - 1):
        window = token_klines[i - 30:i]
        closes = [float(k[4]) for k in window]
        highs = [float(k[2]) for k in window]
        lows = [float(k[3]) for k in window]
        volumes = [float(k[5]) for k in window]

        ema8 = sum(closes[-8:]) / 8
        ema13 = sum(closes[-13:]) / 13
        momentum = ema8 - ema13
        rsi = closes[-1] / (max(closes[-14:]) + 1e-8)  # спрощений
        mid = sum(closes[-20:]) / 20
        stddev = np.std(closes[-20:])
        bb_ratio = (closes[-1] - (mid - 2 * stddev)) / (4 * stddev + 1e-8)

        feature = [momentum, rsi, bb_ratio, np.mean(volumes[-5:])]
        X.append(feature)

        today_price = float(token_klines[i][4])
        tomorrow_price = float(token_klines[i + 1][4])
        y.append(1 if tomorrow_price > today_price * 1.02 else 0)
    return np.array(X), np.array(y)


def train_and_save_model(klines: list[list[float]]):
    X, y = prepare_dataset(klines)
    model = SVC(probability=True)
    model.fit(X, y)
    joblib.dump(model, MODEL_PATH)
    return model


def load_model():
    if not os.path.exists(MODEL_PATH):
        return None
    return joblib.load(MODEL_PATH)


def predict_direction(model, feature_vector: list[float]) -> float:
    return float(model.predict_proba([feature_vector])[0][1])
