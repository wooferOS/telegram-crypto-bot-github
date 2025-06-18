import asyncio
import logging
from typing import Dict, List, Optional


from config import (
    CHAT_ID,
    MIN_EXPECTED_PROFIT,
    MIN_PROB_UP,
    MIN_TRADE_AMOUNT,
)
from services.telegram_service import send_messages

from binance_api import (
    get_binance_balances,
    get_symbol_price,
    get_candlestick_klines,
    get_valid_usdt_symbols,
    get_symbol_precision,
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


def generate_conversion_signals() -> tuple[
    List[Dict[str, float]],
    bool,
    Dict[str, float],
    Dict[str, Dict[str, float]],
    float,
]:
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
        return [], False, {}, {}, balances.get("USDT", 0.0)

    predictions: Dict[str, Dict[str, float]] = {}
    for symbol in get_valid_usdt_symbols():
        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        data = _analyze_pair(pair, model)
        if data:
            predictions[pair] = data

    if not predictions:
        return [], False, portfolio, {}, balances.get("USDT", 0.0)

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
        return [], False, portfolio, predictions, balances.get("USDT", 0.0)

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

    return signals, low_profit, portfolio, predictions, balances.get("USDT", 0.0)


def _compose_failure_message(
    portfolio: Dict[str, float],
    predictions: Dict[str, Dict[str, float]],
    usdt_balance: float,
) -> str:
    """Return detailed failure diagnostics for Telegram."""

    lines: List[str] = ["\u26a0\ufe0f Не вдалося виконати трейд-цикл", ""]

    # SELL diagnostics
    lines.append("🔻 Продаж: ❌")
    profitable = any(
        predictions.get(f"{asset}USDT", {}).get("expected_profit", 0)
        > CONVERSION_MIN_EXPECTED_PROFIT
        for asset in portfolio
    )
    if not profitable:
        lines.append(
            f"– Не знайдено активів з очікуваним прибутком > {CONVERSION_MIN_EXPECTED_PROFIT}"
        )

    count = 0
    for asset, amount in portfolio.items():
        data = predictions.get(f"{asset}USDT")
        if not data:
            continue
        volume = amount * data.get("price", 0)
        if data["expected_profit"] <= 0:
            lines.append(
                f"– {asset} ({amount:.2f}) — expected_profit = {data['expected_profit']:.4f}"
            )
            count += 1
        elif data["prob_up"] < CONVERSION_MIN_PROB_UP:
            lines.append(
                f"– {asset} ({amount:.2f}) — prob_up = {data['prob_up']:.2f} < MIN_PROB_UP"
            )
            count += 1
        elif volume < MIN_TRADE_AMOUNT:
            lines.append(
                f"– Баланс для {asset} ({amount:.2f}) < MIN_TRADE_AMOUNT ({MIN_TRADE_AMOUNT})"
            )
            count += 1
        if count >= 3:
            break

    lines.append("")

    # Conversion diagnostics (placeholder as conversions are not attempted here)
    lines.append("🔁 Конвертація: ❌")
    lines.append("– BTC → USDT не вдалося: LOT_SIZE або інші обмеження")

    lines.append("")

    # BUY diagnostics
    lines.append("💰 Покупка: ❌")
    lines.append(
        f"– Немає USDT після продажу або конвертації (баланс {usdt_balance:.2f})"
    )
    lines.append("– Жоден токен не потрапив до top-3 BUY-кандидатів за score")

    lines.append("")
    lines.append("ℹ️ Поточні фільтри:")
    lines.append(f"– MIN_EXPECTED_PROFIT = {MIN_EXPECTED_PROFIT}")
    lines.append(f"– MIN_PROB_UP = {MIN_PROB_UP}")
    lines.append(f"– MIN_TRADE_AMOUNT = {MIN_TRADE_AMOUNT}")

    return "\n".join(lines)


async def send_conversion_signals(
    signals: List[Dict[str, float]],
    low_profit: bool = False,
    portfolio: Optional[Dict[str, float]] = None,
    predictions: Optional[Dict[str, Dict[str, float]]] = None,
    usdt_balance: float = 0.0,
) -> None:
    """Send conversion suggestions to Telegram."""

    if not signals:
        logger.info("No conversion signals generated")
        message = _compose_failure_message(
            portfolio or {}, predictions or {}, usdt_balance
        )
        await send_messages(int(CHAT_ID), [message])
        return

    lines = []
    for s in signals:
        precision = get_symbol_precision(f"{s['to_symbol']}USDT")
        precision = max(2, min(8, precision))
        to_amount = f"{s['to_amount']:.{precision}f}"
        lines.append(
            f"{s['from_symbol']} → конвертувати {s['to_symbol']}"
            f"\nFROM: {s['from_amount']:.4f} (~{s['from_usdt']:.2f}$)"
            f"\nTO: ≈{to_amount}"
            f"\nОчікуваний прибуток: +{s['profit_pct']:.2f}% (~{s['profit_usdt']:.2f}$)"
            f"\nTP {s['tp']:.4f}, SL {s['sl']:.4f}"
        )
    text = "\n\n".join(lines)
    messages = list(split_telegram_message(text, 4000))
    if low_profit:
        messages.append("\u26a0\ufe0f Очікуваний прибуток низький, конверсія виконана.")
    await send_messages(int(CHAT_ID), messages)


async def main() -> None:
    signals, low_profit, portfolio, predictions, usdt_balance = (
        generate_conversion_signals()
    )
    await send_conversion_signals(
        signals,
        low_profit,
        portfolio=portfolio,
        predictions=predictions,
        usdt_balance=usdt_balance,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
