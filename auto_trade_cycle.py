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
    build_manual_conversion_signal,
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

    actions_made = False

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
            "price": price,
        }

    balances = get_binance_balances()
    symbols_from_balance = {f"{a}USDT" for a in balances if a != "USDT"}
    current_balances = {a: amt for a, amt in balances.items() if a != "USDT"}
    manual_convert: List[tuple[str, float, float]] = []

    for asset, amount in balances.items():
        if asset == "USDT" or amount <= 0:
            continue
        pair = f"{asset}USDT"
        forecast = predictions.get(pair)
        if not forecast:
            continue
        if forecast["expected_profit"] >= MIN_EXPECTED_PROFIT:
            result = sell_asset(pair, amount)
            if result.get("status") != "error":
                actions_made = True
            else:
                conv = convert_to_usdt(asset, amount, forecast)
                if conv is not None:
                    actions_made = True
                else:
                    price = get_symbol_price(pair) or 0.0
                    manual_convert.append((asset, amount, price))

    if manual_convert:
        convert_from_list = []
        for sym, amt, price in manual_convert:
            convert_from_list.append(
                {
                    "symbol": f"{sym}USDT",
                    "quantity": amt,
                    "usdt_value": amt * price,
                }
            )

        buy_candidates = [
            (s, d)
            for s, d in predictions.items()
            if d["prob_up"] >= MIN_PROB_UP
        ]
        buy_candidates.sort(key=lambda x: x[1]["expected_profit"], reverse=True)
        buy_candidates = buy_candidates[: len(convert_from_list)]

        filtered_from: list[dict] = []
        convert_to_suggestions: list[dict] = []
        from_symbols = {item["symbol"].replace("USDT", "") for item in convert_from_list}
        used_targets: set[str] = set()
        j = 0
        for from_item in convert_from_list:
            while j < len(buy_candidates):
                sym, data = buy_candidates[j]
                j += 1
                target_symbol = sym.replace("USDT", "")
                if (
                    target_symbol in from_symbols
                    or target_symbol in used_targets
                    or target_symbol == "USDT"
                ):
                    continue
                price = data.get("price") or get_symbol_price(sym)
                if not price:
                    continue
                qty = from_item["usdt_value"] / price
                balance_amount = current_balances.get(target_symbol, 0)
                if balance_amount >= qty:
                    continue
                expected_profit_usdt = data["tp"] * qty - from_item["usdt_value"]
                if expected_profit_usdt <= 0:
                    continue
                convert_to_suggestions.append({
                    "symbol": sym,
                    "quantity": qty,
                    "expected_profit_usdt": expected_profit_usdt,
                })
                filtered_from.append(from_item)
                used_targets.add(target_symbol)
                break
        convert_from_list = filtered_from
        text = build_manual_conversion_signal(convert_from_list, convert_to_suggestions)
        if text:
            await bot.send_message(chat_id, clean_message(text))

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
                actions_made = True

    if not actions_made:
        message = (
            "ℹ️ Немає активів для торгівлі або конвертації на цій ітерації. "
            "Очікуємо змін на ринку."
        )
        await bot.send_message(chat_id, message)
        logging.info(message)


