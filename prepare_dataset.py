import pandas as pd
import numpy as np
import ta
from binance_api import get_candlestick_klines


def create_dataset() -> pd.DataFrame:
    """Generate training dataset and save to ``data/train.csv``."""
    symbols = ["BTCUSDT", "ETHUSDT"]
    frames = []
    for pair in symbols:
        klines = get_candlestick_klines(pair)
        if not klines:
            continue
        df = pd.DataFrame(
            klines,
            columns=[
                "ts",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "qav",
                "trades",
                "tb_base",
                "tb_quote",
                "ignore",
            ],
        ).astype(float)
        df["rsi"] = ta.momentum.RSIIndicator(close=df["close"]).rsi()
        macd = ta.trend.MACD(close=df["close"])
        df["macd"] = macd.macd()
        bb = ta.volatility.BollingerBands(close=df["close"])
        df["bb_high"] = bb.bollinger_hband()
        df["bb_low"] = bb.bollinger_lband()
        df["vol_change"] = df["volume"].pct_change()
        df["volatility"] = df["close"].pct_change().rolling(5).std()
        df["target"] = df["close"].shift(-1) > df["close"]
        df["symbol"] = pair
        df.dropna(inplace=True)
        frames.append(df)
    dataset = pd.concat(frames, ignore_index=True)
    dataset.to_csv("data/train.csv", index=False)
    return dataset


if __name__ == "__main__":
    create_dataset()
