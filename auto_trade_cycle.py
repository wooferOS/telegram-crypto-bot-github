import logging
import unicodedata
from typing import Dict, List

from binance_api import (
    get_valid_usdt_symbols,
    get_symbol_price,
    get_candlestick_klines,
    get_binance_balances,
    sell_asset,
    convert_to_usdt,
    get_usdt_balance,
    market_buy_symbol_by_amount,
)
from ml_model import load_model, generate_features, predict_prob_up
from utils import dynamic_tp_sl, calculate_expected_profit
from config import MIN_EXPECTED_PROFIT, MIN_PROB_UP, MIN_TRADE_AMOUNT


def clean_message(text: str) -> str:
    """Return ``text`` without surrogate or emoji characters."""

    normalized = unicodedata.normalize("NFKD", text)
    return "".join(
        ch for ch in normalized if ord(ch) <= 0xFFFF and unicodedata.category(ch) != "Cs"
    )


async def auto_trade_cycle(bot, chat_id: int) -> None:
    """Execute one trading cycle based on expected profit forecast."""

    logging.info("\U0001F501 Starting auto_trade_cycle")

    model = load_model()
    predictions: Dict[str, Dict[str, float]] = {}
    symbols = get_valid_usdt_symbols()

    for pair in symbols:
        price = get_symbol_price(pair)
        if not price:
            continue
        klines = get_candlestick_klines(pair)
        if not klines:
            continue
        closes = [float(k[4]) for k in klines]
        tp, sl = dynamic_tp_sl(closes, price)
        try:
            features, _, _ = generate_features(pair)
            prob_up = predict_prob_up(model, features) if model else 0.5
        except Exception:  # noqa: BLE001
            prob_up = 0.5
        expected_profit = calculate_expected_profit(price, tp, 10, sl)
        predictions[pair] = {
            "expected_profit": expected_profit,
            "tp": tp,
            "sl": sl,
            "prob_up": prob_up,
        }

    balances = get_binance_balances()
    manual_convert: List[tuple[str, float, float]] = []

    for asset, amount in balances.items():
        if asset == "USDT" or amount <= 0:
            continue
        pair = f"{asset}USDT"
        forecast = predictions.get(pair)
        if not forecast:
            continue
        if forecast["expected_profit"] > MIN_EXPECTED_PROFIT:
            result = sell_asset(pair, amount)
            if result.get("status") == "error":
                conv = convert_to_usdt(asset, amount)
                if conv is None:
                    price = get_symbol_price(pair) or 0.0
                    manual_convert.append((asset, amount, price))

    if manual_convert:
        lines = [
            "\u26A0\ufe0f \u0421\u0438\u0433\u043d\u0430\u043b: \u0441\u043a\u043e\u043d\u0432\u0435\u0440\u0442\u0443\u0439\u0442\u0435 \u0432\u0440\u0443\u0447\u043d\u0443 \u0430\u043a\u0442\u0438\u0432\u0438 \u043d\u0430 USDT \u0447\u0435\u0440\u0435\u0437 Binance Convert:",
        ]
        for sym, amt, price in manual_convert:
            lines.append(f"- {sym}: {amt} @ {price}")

        top_targets = sorted(
            predictions.items(), key=lambda x: x[1]["expected_profit"], reverse=True
        )[:3]
        if top_targets:
            lines.append("")
            lines.append("\ud83d\udd04 \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u043e\u0432\u0430\u043d\u0456 \u0446\u0456\u043b\u0456 \u0434\u043b\u044f \u043a\u043e\u043d\u0432\u0435\u0440\u0442\u0430\u0446\u0456\u0457:")
            for sym, data in top_targets:
                lines.append(f"- {sym}: ? @ {data['tp']}")
        await bot.send_message(chat_id, clean_message("\n".join(lines)))

    usdt_balance = get_usdt_balance()
    if usdt_balance >= MIN_TRADE_AMOUNT:
        buy_candidates = [
            (sym, data)
            for sym, data in predictions.items()
            if data["prob_up"] >= MIN_PROB_UP
        ]
        buy_candidates.sort(key=lambda x: x[1]["expected_profit"], reverse=True)
        buy_candidates = buy_candidates[:3]
        if buy_candidates:
            amount_per_trade = usdt_balance / len(buy_candidates)
            for sym, _ in buy_candidates:
                market_buy_symbol_by_amount(sym, amount_per_trade)


