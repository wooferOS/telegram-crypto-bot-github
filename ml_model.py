import numpy as np
import pandas as pd
from binance.client import Client
from sklearn.ensemble import RandomForestClassifier
import joblib
import os

MODEL_PATH = "model.joblib"

client = Client(api_key=os.getenv("BINANCE_API_KEY"), api_secret=os.getenv("BINANCE_API_SECRET"))

def load_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    return None

def get_klines(symbol, interval="1h", limit=100):
    data = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"])
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].astype(float)
    return df

def generate_features(symbol):
    df = get_klines(symbol)
    df["close_pct"] = df["close"].pct_change().fillna(0)
    df["volume_change"] = df["volume"].pct_change().fillna(0)
    df["high_low"] = (df["high"] - df["low"]) / df["low"]
    df["target"] = df["close"].shift(-1) > df["close"]
    df.dropna(inplace=True)
    X = df[["close_pct", "volume_change", "high_low"]]
    y = df["target"].astype(int)
    return X.values[-1].reshape(1, -1), X, y

def predict_direction(symbol):
    model = load_model()
    if not model:
        return None
    feature_vector, _, _ = generate_features(symbol)
    prediction = model.predict(feature_vector)
    return "up" if prediction[0] == 1 else "down"
