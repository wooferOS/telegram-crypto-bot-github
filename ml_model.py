import logging
import os
import json
import functools

import joblib
import numpy as np
import pandas as pd
import ta
from binance.client import Client
from sklearn.ensemble import RandomForestClassifier

from binance_api import _to_usdt_pair, is_symbol_valid

MODEL_PATH = "model.joblib"

from config import BINANCE_API_KEY, BINANCE_SECRET_KEY

client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

# Module-level logger
logger = logging.getLogger(__name__)

def load_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    return None

def get_klines(symbol: str, interval: str = "1h", limit: int = 1000):
    # ⛑️ Встановлюємо таймаут у Binance SDK session (5 секунд)
    client.session.request = functools.partial(client.session.request, timeout=5)
    try:
        data = client.get_klines(
            symbol=f"{symbol}USDT",
            interval=interval,
            limit=limit,
        )
        return data
    except Exception as e:
        logger.warning(f"[dev] ⚠️ get_klines() failed for {symbol}: {e}")
        return []

def add_technical_indicators(df):
    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"]).rsi()
    df["macd"] = ta.trend.MACD(close=df["close"]).macd()
    df["ema"] = ta.trend.EMAIndicator(close=df["close"], window=14).ema_indicator()
    df["sma"] = ta.trend.SMAIndicator(close=df["close"], window=14).sma_indicator()
    df["atr"] = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"]).average_true_range()
    return df

def generate_features(symbol: str):
    """Generate ML features for the given trading symbol."""
    try:
        data = get_klines(symbol)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ get_klines failed for {symbol}: {e}")
        raise
    if not data:
        raise ValueError(f"\u26A0\uFE0F No data for {symbol}")

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


TRADE_MODEL_PATH = "trade_model.joblib"


def train_model_from_history(history_file: str = "trade_history.json"):
    """Train RandomForest model using recorded trade history."""

    if not os.path.exists(history_file):
        logging.warning("[dev] trade_history.json not found")
        return None
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # pragma: no cover - simple IO
        logging.warning("[dev] Failed to load history: %s", exc)
        return None

    if not data:
        logging.warning("[dev] Empty trade history")
        return None

    df = pd.DataFrame(data)
    features = [
        "expected_profit",
        "prob_up",
        "score",
        "whale_alert",
        "volume",
        "rsi",
        "trend",
        "previous_gain",
    ]
    for col in features:
        if col not in df:
            df[col] = 0.0
    if "success" in df:
        y = df["success"].astype(int)
    else:
        y = (df.get("sell_profit", 0) > 0).astype(int)

    X = df[features].fillna(0)

    model = RandomForestClassifier(n_estimators=150, random_state=42)
    model.fit(X, y)
    joblib.dump(model, TRADE_MODEL_PATH)
    return model


def _load_trade_model():
    if os.path.exists(TRADE_MODEL_PATH):
        try:
            return joblib.load(TRADE_MODEL_PATH)
        except Exception:
            return None
    return None


def predict_trade_success(token_data: dict) -> float:
    """Return probability of trade success based on history model."""

    model = _load_trade_model()
    if not model:
        return 0.5
    df = pd.DataFrame([token_data])
    df = df.fillna(0)
    try:
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(df)[0][1]
            return float(proba)
        pred = model.predict(df)[0]
        return 1.0 if int(pred) == 1 else 0.0
    except Exception:
        return 0.5
