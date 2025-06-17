import asyncio
import logging
import os
from typing import Dict, List, Optional

from aiogram import Bot

from binance_api import (
    get_binance_balances,
    get_symbol_price,
    get_candlestick_klines,
    get_valid_usdt_symbols,
)
from ml_model import load_model, generate_features, predict_prob_up
from utils import dynamic_tp_sl, calculate_expected_profit
from daily_analysis import split_telegram_message
from config import (
    CHAT_ID,
    MIN_EXPECTED_PROFIT,
    MIN_PROB_UP,
)

logger = logging.getLogger(__name__)


def _analyze_pair(pair: str, model) -> Optional[Dict[str, float]]:
    """Return price analysis data for ``pair`` or ``None`` on failure."""

    price = get_symbol_price(pair)
    if price is None:
        return None

    klines = get_candlestick_klines(pair)
    if not klines:
        return None

    closes = [float(k[4]) for k in klines]
    tp, sl = dynamic_tp_sl(closes, price)

    try:
        features, _, _ = generate_features(pair)
        prob_up = predict_prob_up(model, features) if model else 0.5
    except Exception:  # noqa: BLE001
        prob_up = 0.5

    expected_profit = calculate_expected_profit(price, tp, amount=10, sl_price=sl)
    return {
        "price": price,
        "tp": tp,
        "sl": sl,
        "prob_up": prob_up,
        "expected_profit": expected_profit,
    }


def generate_conversion_signals() -> List[Dict[str, float]]:
    """Analyze portfolio and propose asset conversions."""

    model = load_model()
    balances = get_binance_balances()
    portfolio = {
        a: amt
        for a, amt in balances.items()
        if a not in {"USDT", "BUSD"} and amt > 0
    }
    if not portfolio:
        return []

    predictions: Dict[str, Dict[str, float]] = {}
    for symbol in get_valid_usdt_symbols():
        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        data = _analyze_pair(pair, model)
        if data:
            predictions[pair] = data

    if not predictions:
        return []

    best_pair, best_data = max(
        (
            (p, d)
            for p, d in predictions.items()
            if d["prob_up"] >= MIN_PROB_UP
        ),
        key=lambda x: x[1]["expected_profit"],
        default=(None, None),
    )

    if not best_pair or best_data["expected_profit"] < MIN_EXPECTED_PROFIT:
        return []

    signals: List[Dict[str, float]] = []
    for asset, amount in portfolio.items():
        pair = asset if asset.endswith("USDT") else f"{asset}USDT"
        current = predictions.get(pair)
        if not current:
            continue
        if best_data["expected_profit"] <= current["expected_profit"]:
            continue

        from_price = current["price"]
        from_usdt = amount * from_price
        to_qty = from_usdt / best_data["price"]
        diff = best_data["expected_profit"] - current["expected_profit"]
        profit_pct = (diff / 10) * 100
        profit_usdt = (diff / 10) * from_usdt

        signals.append(
            {
                "from_symbol": asset,
                "to_symbol": best_pair.replace("USDT", ""),
                "from_amount": amount,
                "from_usdt": from_usdt,
                "to_amount": to_qty,
                "profit_pct": profit_pct,
                "profit_usdt": profit_usdt,
                "tp": best_data["tp"],
                "sl": best_data["sl"],
            }
        )

    return signals


async def send_conversion_signals(signals: List[Dict[str, float]]) -> None:
    """Send conversion suggestions to Telegram."""

    if not signals:
        logger.info("No conversion signals generated")
        return

    bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
    lines = []
    for s in signals:
        lines.append(
            f"{s['from_symbol']} → конвертувати {s['to_symbol']}"
            f"\nFROM: {s['from_amount']:.4f} (~{s['from_usdt']:.2f}$)"
            f"\nTO: ≈{s['to_amount']:.4f}"
            f"\nОчікуваний прибуток: +{s['profit_pct']:.2f}% (~{s['profit_usdt']:.2f}$)"
            f"\nTP {s['tp']:.4f}, SL {s['sl']:.4f}"
        )
    text = "\n\n".join(lines)
    for part in split_telegram_message(text, 4000):
        await bot.send_message(CHAT_ID, part)


async def main() -> None:
    signals = generate_conversion_signals()
    await send_conversion_signals(signals)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
