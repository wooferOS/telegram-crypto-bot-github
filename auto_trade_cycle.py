import asyncio
import logging
from typing import Dict, List, Optional


from config import TELEGRAM_TOKEN, CHAT_ID
from services.telegram_service import send_messages

from binance_api import (
    get_binance_balances,
    get_symbol_price,
    get_candlestick_klines,
    get_valid_usdt_symbols,
)
from ml_model import load_model, generate_features, predict_prob_up
from utils import dynamic_tp_sl, calculate_expected_profit
from daily_analysis import split_telegram_message

# These thresholds are more lenient for manual conversion suggestions
# Generate signals even for modest opportunities
CONVERSION_MIN_EXPECTED_PROFIT = 0.01
CONVERSION_MIN_PROB_UP = 0.5


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


def generate_conversion_signals() -> tuple[List[Dict[str, float]], bool]:
    """Analyze portfolio and propose asset conversions.

    Returns a list of conversion suggestions and a flag indicating
    whether the expected profit was below ``CONVERSION_MIN_EXPECTED_PROFIT``.
    """

    model = load_model()
    balances = get_binance_balances()
    portfolio = {
        a: amt for a, amt in balances.items() if a not in {"USDT", "BUSD"} and amt > 0
    }
    if not portfolio:
        return [], False

    predictions: Dict[str, Dict[str, float]] = {}
    for symbol in get_valid_usdt_symbols():
        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        data = _analyze_pair(pair, model)
        if data:
            predictions[pair] = data

    if not predictions:
        return [], False

    best_pair, best_data = max(
        (
            (p, d)
            for p, d in predictions.items()
            if d["expected_profit"] > 0 and d["prob_up"] > 0
        ),
        key=lambda x: x[1]["expected_profit"],
        default=(None, None),
    )

    if not best_pair:
        return [], False

    low_profit = False
    if best_data["expected_profit"] <= CONVERSION_MIN_EXPECTED_PROFIT:
        logger.info(
            "\u26a0\ufe0f Low expected profit %.4f USDT for %s",
            best_data["expected_profit"],
            best_pair,
        )
        low_profit = True

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

    if not signals and best_pair:
        # Fallback: convert 90% of the highest-value asset to the best pair
        portfolio_pairs = [
            (
                asset,
                amount,
                predictions.get(asset if asset.endswith("USDT") else f"{asset}USDT"),
            )
            for asset, amount in portfolio.items()
            if predictions.get(asset if asset.endswith("USDT") else f"{asset}USDT")
        ]
        if portfolio_pairs:
            top_asset, amount, current = max(
                portfolio_pairs, key=lambda x: x[1] * x[2]["price"]
            )
            from_amount = amount * 0.9
            from_price = current["price"]
            from_usdt = from_amount * from_price
            to_qty = from_usdt / best_data["price"]
            diff = best_data["expected_profit"] - current["expected_profit"]
            profit_pct = (diff / 10) * 100
            profit_usdt = (diff / 10) * from_usdt

            signals.append(
                {
                    "from_symbol": top_asset,
                    "to_symbol": best_pair.replace("USDT", ""),
                    "from_amount": from_amount,
                    "from_usdt": from_usdt,
                    "to_amount": to_qty,
                    "profit_pct": profit_pct,
                    "profit_usdt": profit_usdt,
                    "tp": best_data["tp"],
                    "sl": best_data["sl"],
                }
            )

    return signals, low_profit


async def send_conversion_signals(
    signals: List[Dict[str, float]], low_profit: bool = False
) -> None:
    """Send conversion suggestions to Telegram."""

    if not signals:
        logger.info("No conversion signals generated")
        await send_messages(
            TELEGRAM_TOKEN,
            int(CHAT_ID),
            [
                "\u26a0\ufe0f \u041d\u0435\u043c\u0430\u0454 \u0430\u043a\u0442\u0438\u0432\u0456\u0432 \u0434\u043b\u044f \u043f\u0440\u043e\u0434\u0430\u0436\u0443 / \u043a\u0443\u043f\u0456\u0432\u043b\u0456"
            ],
        )
        return

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
    messages = list(split_telegram_message(text, 4000))
    if low_profit:
        messages.append("\u26a0\ufe0f Очікуваний прибуток низький, конверсія виконана.")
    await send_messages(TELEGRAM_TOKEN, int(CHAT_ID), messages)


async def main() -> None:
    signals, low_profit = generate_conversion_signals()
    await send_conversion_signals(signals, low_profit)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
