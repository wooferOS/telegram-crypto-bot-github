import logging
import os

import joblib
import numpy as np
import pandas as pd
import ta
from binance.client import Client
from sklearn.ensemble import RandomForestClassifier

from binance_api import _to_usdt_pair, is_symbol_valid
from config import BINANCE_API_KEY, BINANCE_API_SECRET

MODEL_PATH = "model.joblib"

client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

def load_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    return None

def get_klines(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    """Fetch klines for a symbol with basic error handling."""
    pair = _to_usdt_pair(symbol)
    if not is_symbol_valid(symbol):
        logging.warning("%s not valid for klines", pair)
        return pd.DataFrame()
    try:
        data = client.get_klines(symbol=pair, interval=interval, limit=limit)
    except Exception as e:  # noqa: BLE001
        logging.warning("\u26A0\uFE0F Binance error for %s: %s", pair, e)
        return pd.DataFrame()

    df = pd.DataFrame(
        data,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
            "ignore",
        ],
    )
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].astype(float)
    return df

def add_technical_indicators(df):
    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"]).rsi()
    df["macd"] = ta.trend.MACD(close=df["close"]).macd()
    df["ema"] = ta.trend.EMAIndicator(close=df["close"], window=14).ema_indicator()
    df["sma"] = ta.trend.SMAIndicator(close=df["close"], window=14).sma_indicator()
    df["atr"] = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"]).average_true_range()
    return df

def generate_features(symbol: str):
    """Generate ML features for the given trading symbol."""
    df = get_klines(symbol)
    if df.empty:
        raise ValueError(f"\u26A0\uFE0F No data for {symbol}")

    df = add_technical_indicators(df)

    df["close_pct"] = df["close"].pct_change()
    df["volume_change"] = df["volume"].pct_change()
    df["high_low"] = (df["high"] - df["low"]) / df["low"]
    df["target"] = df["close"].shift(-1) > df["close"]

    df.dropna(inplace=True)

    X = df[["close_pct", "volume_change", "high_low", "rsi", "macd", "ema", "sma", "atr"]].copy()
    y = df["target"].astype(int)

    # 🧼 Очистити інфініті та NaN
    X.replace([np.inf, -np.inf], np.nan, inplace=True)
    X.dropna(inplace=True)
    y = y[-len(X):]

    return X.values[-1].reshape(1, -1), X, y

def predict_direction(model, feature_vector):
    """Прогнозує напрямок руху (up/down) на основі переданої моделі та фічей."""
    prediction = model.predict(np.asarray(feature_vector).reshape(1, -1))
    return "up" if prediction[0] == 1 else "down"


def predict_prob_up(model, feature_vector) -> float:
    """Return probability of price going up using ``model``."""
    try:
        if hasattr(model, "predict_proba"):
            probs = model.predict_proba(np.asarray(feature_vector).reshape(1, -1))
            return float(probs[0][1])
        direction = predict_direction(model, feature_vector)
        return 1.0 if direction == "up" else 0.0
    except Exception as exc:  # noqa: BLE001
        logging.warning("ML prediction failed: %s", exc)
        return 0.5
