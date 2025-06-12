import os
from typing import List, Dict
from binance.client import Client

from binance_api import get_symbol_price, get_candlestick_klines as get_klines
import numpy as np
from ml_model import load_model, generate_features, predict_prob_up
from utils import dynamic_tp_sl, calculate_expected_profit

client = Client(api_key=os.getenv("BINANCE_API_KEY"), api_secret=os.getenv("BINANCE_API_SECRET"))


def get_valid_symbols() -> List[str]:
    """Return all active USDT trading pairs from Binance."""
    return [
        s["symbol"]
        for s in client.get_exchange_info()["symbols"]
        if s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
        and s["isSpotTradingAllowed"]
    ]


def estimate_profit(symbol: str) -> float:
    """Estimate expected profit for ``symbol`` using dynamic TP/SL."""
    price = get_symbol_price(symbol)
    if price is None:
        return 0.0
    klines = get_klines(symbol)
    if not klines:
        return 0.0
    closes = [float(k[4]) for k in klines]
    tp, sl = dynamic_tp_sl(closes, price)
    return calculate_expected_profit(price, tp, amount=10, sl_price=sl)


def get_candidates(symbols: List[str]) -> List[Dict[str, float]]:
    """Return promising tokens ranked by ML probability."""
    model = load_model()
    if not model:
        print("\u26A0\ufe0f Модель недоступна")
    candidates: List[Dict[str, float]] = []
    for symbol in symbols:
        try:
            feature_vector, _, _ = generate_features(symbol)
            fv = np.asarray(feature_vector).reshape(1, -1)
            prob_up = predict_prob_up(model, fv) if model else 0.5
            expected_profit = estimate_profit(symbol)
            if prob_up > 0.5 and expected_profit > 0.005:
                candidates.append({
                    "symbol": symbol,
                    "expected_profit": expected_profit,
                    "prob_up": prob_up,
                })
        except Exception as e:  # noqa: BLE001
            print(f"\u26A0\ufe0f \u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e {symbol}: {e}")
            continue
    return candidates


if __name__ == "__main__":
    symbols = get_valid_symbols()
    tokens = get_candidates(symbols)
    for t in tokens:
        print(f"{t['symbol']}: prob_up={t['prob_up']:.2f}, expected={t['expected_profit']}")
