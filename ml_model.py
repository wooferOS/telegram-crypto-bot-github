import numpy as np
import pandas as pd
from binance.client import Client
from sklearn.ensemble import RandomForestClassifier
import joblib
import os
import ta

MODEL_PATH = "model.joblib"

client = Client(api_key=os.getenv("BINANCE_API_KEY"), api_secret=os.getenv("BINANCE_API_SECRET"))

def load_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    return None

def get_klines(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    """Fetch klines for a symbol with basic error handling."""
    try:
        data = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception as e:  # noqa: BLE001
        print(f"\u26A0\uFE0F Binance error for {symbol}: {e}")
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

    X = df[["close_pct", "volume_change", "high_low", "rsi", "macd", "ema", "sma", "atr"]]
    y = df["target"].astype(int)

    # 🧼 Очистити інфініті та NaN
    X.replace([np.inf, -np.inf], np.nan, inplace=True)
    X.dropna(inplace=True)
    y = y[-len(X):]

    return X.values[-1].reshape(1, -1), X, y

def predict_direction(model, feature_vector):
    """Прогнозує напрямок руху (up/down) на основі переданої моделі та фічей."""
    # ensure feature_vector has the correct shape for the model
    prediction = model.predict(np.asarray(feature_vector).reshape(1, -1))
    return "up" if prediction[0] == 1 else "down"
