# ✅ Еталонна логіка GPT-звіту /zarobyty (v2.0) — повна реалізація
# Мета: максимізувати прибуток за добу, діючи в рамках поточного балансу Binance

import datetime
import pytz
import statistics
import logging
import os
from binance.client import Client

from binance_api import (
    get_binance_balances,
    get_symbol_price,
    get_candlestick_klines as get_price_history,
    get_candlestick_klines as get_klines,
    get_recent_trades as get_my_trades,
    get_top_tokens,
    load_tradable_usdt_symbols,
    get_usdt_to_uah_rate,
    place_market_order,
    place_limit_sell_order,
    get_open_orders,
    update_tp_sl_order,
    log_tp_sl_change,
)
from binance_api import get_candlestick_klines
from gpt_utils import ask_gpt
from utils import (
    convert_to_uah,
    calculate_rr,
    calculate_expected_profit,
    calculate_indicators,
    kelly_fraction,
    dynamic_tp_sl,
    advanced_buy_filter,
    get_sector,
    analyze_btc_correlation,
    _ema,
)
from history import _load_history, get_failed_tokens_history
from coingecko_api import get_sentiment
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from ml_model import (
    load_model,
    generate_features,
    predict_direction,
    predict_prob_up,
)

client = Client(api_key=os.getenv("BINANCE_API_KEY"), api_secret=os.getenv("BINANCE_API_SECRET"))


def get_valid_symbols() -> list[str]:
    """Отримати всі активні спотові пари до USDT з Binance"""

    return [
        s["symbol"]
        for s in client.get_exchange_info()["symbols"]
        if s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
        and s["isSpotTradingAllowed"]
    ]

symbols = get_valid_symbols()

logger = logging.getLogger(__name__)

# Global minimum thresholds
MIN_EXPECTED_PROFIT = 0.005  # 0.5%
MIN_PROB_UP = 0.55
MIN_VOLUME = 100_000

def split_telegram_message(text: str, chunk_size: int = 4000) -> list[str]:
    """Split long text into chunks suitable for Telegram messages."""
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def send_message_parts(bot, chat_id: int, text: str) -> None:
    """Send ``text`` to Telegram in chunks not exceeding ``chunk_size``."""
    for part in split_telegram_message(text, 4000):
        await bot.send_message(chat_id, part)



def _maybe_update_orders(symbol: str, new_tp: float, new_sl: float) -> bool:
    """Check existing TP/SL for ``symbol`` and update if price changed."""

    pair = f"{symbol.upper()}USDT"
    orders = get_open_orders(pair)
    if not orders:
        return False

    tp_price = None
    sl_price = None
    for o in orders:
        if o.get("side") == "SELL" and o.get("type") == "LIMIT":
            tp_price = float(o.get("price", 0))
        if o.get("side") == "SELL" and o.get("type") == "STOP_LOSS_LIMIT":
            sl_price = float(o.get("stopPrice", 0))

    if tp_price is None and sl_price is None:
        return False

    update_needed = False
    if tp_price is not None and abs(tp_price - new_tp) / tp_price > 0.015:
        update_needed = True
    if sl_price is not None and abs(sl_price - new_sl) / sl_price > 0.015:
        update_needed = True

    if update_needed:
        update_tp_sl_order(symbol, new_tp, new_sl)
        log_tp_sl_change(symbol, "updated", new_tp, new_sl)
        return True
    return False


def execute_buy_order(symbol: str, amount_usdt: float):
    try:
        price = get_symbol_price(symbol)
        quantity = round(amount_usdt / price, 5)
        buy_order = place_market_order(symbol, "BUY", amount_usdt)
        if not buy_order or (isinstance(buy_order, dict) and "error" in buy_order):
            logger.warning(f"⚠️ Купівля {symbol} не виконана")
            return

        logger.info(f"✅ Куплено {quantity} {symbol} по ринку")

        target_profit_percent = 10
        take_profit_price = round(price * (1 + target_profit_percent / 100), 5)

        tp_order = place_limit_sell_order(f"{symbol.upper()}USDT", quantity, take_profit_price)
        if isinstance(tp_order, dict) and tp_order.get("error"):
            logger.warning(f"⚠️ TP для {symbol} не виставлено")
        else:
            logger.info(f"✅ TP для {symbol}: {take_profit_price}")

    except Exception as e:
        logger.error(f"❌ Помилка під час покупки {symbol}: {e}")


def calculate_expected_profit(
    price: float,
    tp_price: float,
    amount: float,
    sl_price: float | None = None,
    success_rate: float = 0.75,
    fee: float = 0.001,
) -> float:
    """Return expected profit adjusted for fees and risk."""

    if price <= 0 or tp_price <= price:
        return 0.0

    gross = (tp_price - price) / price * amount
    loss = ((price - sl_price) / price * amount) if sl_price and sl_price < price else 0

    net_profit = gross * (1 - 2 * fee)
    expected = net_profit * success_rate - loss * (1 - success_rate)
    return round(expected, 4)


def score_token(token: dict) -> float:
    """Return aggregated score for token buy candidate."""

    return (
        token.get("risk_reward", 0) * 2
        + (token.get("momentum", 0) > 0) * 1.5
        + token.get("sector_score", 0)
        + token.get("success_score", 0) * 2
        + token.get("orderbook_bias", 0) * 1.2
        + (-token.get("btc_corr", 0)) * 1
    )


def enrich_with_metrics(candidates: list[dict]) -> list[dict]:
    """Add TP/SL, indicators and other metrics to raw token data."""

    enriched = []
    for token in candidates:
        symbol = token.get("symbol") or token.get("baseAsset")
        if not symbol:
            continue

        price = token.get("price") or get_symbol_price(symbol)
        klines = get_klines(symbol)
        indicators = calculate_indicators(klines)
        rr = token.get("risk_reward")
        if rr is None:
            rr = calculate_rr(klines)

        closes = [float(k[4]) for k in klines]
        tp_def, sl_def = dynamic_tp_sl(closes, price)

        enriched.append(
            {
                "symbol": symbol,
                "price": price,
                "risk_reward": rr,
                "tp_price": token.get("tp_price") or tp_def,
                "sl_price": token.get("sl_price") or sl_def,
                "momentum": token.get("momentum", indicators.get("momentum", 0)),
                "indicators": indicators,
                "sector_score": token.get("sector_score", 0),
                "success_score": get_success_score(symbol),
                "orderbook_bias": token.get("orderbook_bias", 0),
                "btc_corr": token.get("btc_corr") if "btc_corr" in token else analyze_btc_correlation(symbol),
            }
        )
    return enriched


def get_success_score(symbol: str) -> float:
    """Calculate average profit per trade for ``symbol`` from history."""

    history = _load_history()
    trades = [h for h in history if h.get("symbol", "").upper() == symbol.upper()]
    if not trades:
        return 0.0
    profit = 0.0
    last_buy = None
    for t in trades:
        side = t.get("side", "").upper()
        price = float(t.get("price", 0))
        qty = float(t.get("qty", 0))
        if side == "BUY":
            last_buy = price
        elif side == "SELL" and last_buy is not None:
            profit += (price - last_buy) * qty
            last_buy = None
    return round(profit / len(trades), 2)

def generate_zarobyty_report() -> tuple[str, InlineKeyboardMarkup, list, str]:
    balances = get_binance_balances()
    usdt_balance = balances.get("USDT", 0) or 0
    now = datetime.datetime.now(pytz.timezone("Europe/Kyiv"))
    token_data = []

    for symbol, amount in balances.items():
        if symbol == "USDT" or amount == 0:
            continue
        if symbol not in load_tradable_usdt_symbols():
            continue

        price = get_symbol_price(symbol)
        uah_value = convert_to_uah(price * amount)
        klines = get_klines(symbol)
        trades = get_my_trades(f"{symbol}USDT")
        indicators = calculate_indicators(klines)
        average_buy_price = sum([float(t['price']) * float(t['qty']) for t in trades]) / sum([float(t['qty']) for t in trades]) if trades else price
        pnl_percent = ((price - average_buy_price) / average_buy_price) * 100
        rr = calculate_rr(klines)
        volume_24h = sum(float(k[5]) for k in get_price_history(symbol)) if klines else 0
        sector = get_sector(symbol)
        btc_corr = analyze_btc_correlation(symbol)

        token_data.append({
            "symbol": symbol,
            "amount": amount,
            "quantity": amount,
            "uah_value": round(uah_value, 2),
            "price": price,
            "pnl": round(pnl_percent, 2),
            "rr": rr,
            "indicators": indicators,
            "volume": volume_24h,
            "sector": sector,
            "btc_corr": btc_corr
        })

    # 🔻 Sell recommendations
    sell_recommendations = [t for t in token_data if t["pnl"] >= 1.0]
    sell_symbols = {t["symbol"] for t in sell_recommendations}
    exchange_rate_uah = get_usdt_to_uah_rate()
    usdt_from_sales = sum([t["uah_value"] for t in sell_recommendations]) / exchange_rate_uah
    available_usdt = round(usdt_balance + usdt_from_sales, 2)

    # 🔍 Candidates to analyze
    symbols_from_balance = set(t['symbol'].upper() for t in token_data)
    market_symbols = set(t["symbol"].upper() for t in get_top_tokens(limit=50))
    symbols_to_analyze = symbols_from_balance.union(market_symbols)
    valid_pairs = {s.replace("USDT", "").upper() for s in get_valid_symbols()}
    symbols_to_analyze = [s for s in symbols_to_analyze if s in valid_pairs]

    enriched_tokens = []
    model = load_model()
    for symbol in symbols_to_analyze:
        price = get_symbol_price(symbol)
        klines = get_klines(symbol)
        if not klines:
            continue
        try:
            indicators = calculate_indicators(klines)
        except Exception:
            continue
        rr = calculate_rr(klines)
        sector = get_sector(symbol)
        btc_corr = analyze_btc_correlation(symbol)
        closes = [float(k[4]) for k in klines]

        tp, sl = dynamic_tp_sl(closes, price)
        ema8 = indicators.get("EMA_8", 0)
        ema13 = indicators.get("EMA_13", 0)
        momentum = ema8 - ema13
        rsi = indicators.get("RSI", 50)
        mid = statistics.mean(closes[-20:])
        stddev = statistics.pstdev(closes[-20:])
        bb_ratio = (closes[-1] - (mid - 2 * stddev)) / (4 * stddev + 1e-8)
        volume_avg = statistics.fmean([float(k[5]) for k in klines[-5:]])

        prob_up = 0.5
        try:
            feature_vector, _, _ = generate_features(symbol)
            if model:
                direction = predict_direction(model, feature_vector)
                prob_up = 1.0 if direction == "up" else 0.0
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ ML error for {symbol}: {e}")
            prob_up = 0.5

        success_score = get_success_score(symbol)
        orderbook_bias = 0  # можна реалізувати пізніше
        expected_profit = calculate_expected_profit(price, tp, amount=10, sl_price=sl)
        volume_24h = sum(float(k[5]) for k in get_price_history(symbol)) if klines else 0
        score = rr * 2 + momentum + success_score + (-btc_corr) + prob_up * 2

        enriched_tokens.append({
            "symbol": symbol,
            "price": price,
            "risk_reward": rr,
            "tp_price": tp,
            "sl_price": sl,
            "momentum": momentum,
            "sector_score": 0,
            "success_score": success_score,
            "orderbook_bias": orderbook_bias,
            "btc_corr": btc_corr,
            "indicators": indicators,
            "score": score,
            "expected_profit": expected_profit,
            "prob_up": prob_up,
            "volume": volume_24h,
        })

    # ✅ Apply advanced filtering
    buy_candidates = [
        t
        for t in enriched_tokens
        if advanced_buy_filter(t)
        and t.get("prob_up", 0) >= MIN_PROB_UP
        and t.get("expected_profit", 0) >= MIN_EXPECTED_PROFIT
    ]
    for t in buy_candidates:
        t["score"] = score_token(t)

    buy_plan = []
    remaining = available_usdt
    updates: list[tuple[str, float, float]] = []
    candidate_lines: list[str] = []

    if not buy_candidates:
        print("⚠️ No buy candidates passed advanced filters. Using fallback.")
        fallback = [
            token
            for token in enriched_tokens
            if token.get("expected_profit", 0) > 0
            and token.get("volume", 0) > MIN_VOLUME
        ]
        fallback.sort(key=lambda x: x["score"], reverse=True)
        if fallback:
            best = fallback[0]
            buy_plan.append(
                {
                    "symbol": best["symbol"],
                    "expected_profit": best["expected_profit"],
                    "prob_up": best["prob_up"],
                    "note": "🟡 Слабкий сигнал — fallback",
                }
            )
            candidate_lines.append(f"{best['symbol']} (fallback)")
        top_buy_candidates = []
    else:
        top_buy_candidates = sorted(buy_candidates, key=lambda t: t["score"], reverse=True)[:5]

        for token in top_buy_candidates:
            if remaining < 1:
                break
            rr = token.get("risk_reward", 1.5)
            kelly = kelly_fraction(0.75, rr)
            amount = round(min(remaining, available_usdt * kelly), 2)

            token["amount_usdt"] = amount
            tp = token["tp_price"]
            sl = token["sl_price"]
            price = token["price"]
            token["expected_profit"] = calculate_expected_profit(price, tp, amount, sl)

            if _maybe_update_orders(token["symbol"], tp, sl):
                updates.append((f"{token['symbol']}USDT", tp, sl))

            buy_plan.append(token)
            remaining -= amount

            if len(candidate_lines) < 3:
                candidate_lines.append(
                    f"{token['symbol']} {amount} USDT (EP: {token.get('expected_profit')})"
                )

    if not buy_plan and buy_candidates:
        buy_plan.append(buy_candidates[0])

    # 📝 Final report
    report_lines = []
    report_lines.append(f"🕒 Звіт сформовано: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
    report_lines.append("💰 Баланс:")
    for t in token_data:
        report_lines.append(f"{t['symbol']}: {t['amount']} ≈ ~{t['uah_value']}₴")
    total_uah = round(sum([t['uah_value'] for t in token_data]) + convert_to_uah(usdt_balance), 2)
    report_lines.append(f"Загальний баланс: {total_uah}₴\n⸻")

    report_lines.append("📉 Що продаємо:")
    if sell_recommendations:
        for t in sell_recommendations:
            report_lines.append(f"{t['symbol']}: {t['amount']} ≈ ~{t['uah_value']}₴ (PnL = {t['pnl']}%)")
    else:
        report_lines.append("(порожньо)")
    report_lines.append("\n⸻")

    if candidate_lines:
        report_lines.append("📈 Що купуємо:")
        report_lines.extend(candidate_lines)
    else:
        report_lines.append("📈 Що купуємо: (порожньо)")
    report_lines.append("\n⸻")

    total_expected_profit = sum(t.get("expected_profit", 0) for t in buy_plan)
    expected_profit_usdt = round(total_expected_profit, 2)
    expected_profit_uah = convert_to_uah(expected_profit_usdt)
    report_lines.append(f"💹 Очікуваний прибуток: {expected_profit_usdt} USDT ≈ {expected_profit_uah}₴ за 24г")

    report = "\n".join(report_lines)
    keyboard = InlineKeyboardMarkup(row_width=2)

    for token in sell_recommendations:
        keyboard.insert(
            InlineKeyboardButton(
                text=f"🔴 Продати {token['symbol']}",
                callback_data=f"sell:{token['symbol']}"
            )
        )

    for token in buy_plan:
        keyboard.insert(
            InlineKeyboardButton(
                text=f"🟢 Купити {token['symbol']}",
                callback_data=f"buy:{token['symbol']}"
            )
        )

    return report, keyboard, updates, ""




def generate_daily_stats_report() -> str:
    """Temporary stub for daily stats command."""
    return "\u23F3 \u041F\u043E\u043A\u0438 \u0449\u043E \u0449\u043E\u0434\u0435\u043D\u043D\u0438\u0439 \u0437\u0432\u0456\u0442 \u043D\u0435 \u0440\u0435\u0430\u043B\u0456\u0437\u043E\u0432\u0430\u043D\u043E."


async def daily_analysis_task(bot, chat_id: int) -> None:
    """Run daily analysis and notify about TP/SL updates."""
    report, _, updates, gpt_text = generate_zarobyty_report()
    full_text = f"{report}\n\n{gpt_text}"
    await send_message_parts(bot, chat_id, full_text)
    for symbol, tp_price, sl_price in updates:
        await bot.send_message(
            chat_id,
            f"\u267B\ufe0f Ордер оновлено: {symbol} — новий TP: {tp_price}, SL: {sl_price}"
        )


async def send_zarobyty_forecast(bot, chat_id: int) -> None:
    """Send the GPT forecast separately, splitting long text into chunks."""
    _, _, _, gpt_text = generate_zarobyty_report()
    for part in split_telegram_message(gpt_text, 4000):
        await bot.send_message(chat_id, part)

# Adaptive filters for selecting buy candidates
from utils import (
    calculate_indicators,
    get_risk_reward_ratio,
    get_correlation_with_btc,
)


def smart_buy_filter(candidates: list[dict]) -> list[dict]:
    """Filter buy candidates using expected profit and score."""

    filtered: list[dict] = []
    failed = get_failed_tokens_history()
    for token in candidates:
        if (
            token.get("expected_profit", 0) < 0.5
            or token.get("score", 0) < 4
            or token.get("tp_price") is None
            or token.get("sl_price") is None
        ):
            continue
        if token.get("symbol") in failed:
            continue
        filtered.append(token)

    # 🔁 Remove duplicate tokens by symbol
    seen = set()
    unique_filtered = []
    for t in filtered:
        sym = t.get("symbol")
        if sym in seen:
            continue
        seen.add(sym)
        unique_filtered.append(t)

    filtered = unique_filtered

    return sorted(filtered, key=lambda x: x.get("score", 0), reverse=True)


def advanced_buy_filter(token: dict) -> bool:
    """Return True if token passes advanced technical filters."""

    indicators = token.get("indicators", {})
    rsi = indicators.get("RSI", 50)
    macd_cross = indicators.get("MACD_CROSS", False)
    bb_touch = indicators.get("BB_LOWER_TOUCH", False)
    momentum = token.get("momentum", 0)
    rr = token.get("risk_reward", 0)

    return (
        rsi < 40
        and macd_cross
        and bb_touch
        and momentum > 0
        and rr > 1.5
    )


def filter_adaptive_smart_buy(candidates):
    filtered = []
    required_fields = {
        "risk_reward",
        "volatility_7d",
        "ema_cross",
        "momentum",
    }
    for token in candidates:
        missing = [f for f in required_fields if f not in token]
        if missing or "indicators" not in token or "rsi" not in token.get("indicators", {}):
            logger.debug(
                "Skipping %s due to missing fields: %s",
                token.get("symbol"),
                ",".join(missing),
            )
            continue

        rsi = token["indicators"].get("rsi", 50)
        rr = token.get("risk_reward", 0)

        if rsi < 40 and rr > 1.5:
            filtered.append(token)
    return filtered


def filter_fallback_best_candidates(candidates, max_results=3):
    sorted_candidates = sorted(
        candidates,
        key=lambda x: (
            x.get("risk_reward", 0),
            -x.get("indicators", {}).get("rsi", 50),
            x.get("volume_change_24h", 0),
        ),
        reverse=True,
    )
    return sorted_candidates[:max_results]


def demo_candidates_loop(symbols: list[str]) -> list[dict]:
    """Example loop demonstrating ML screening with safe fallbacks."""

    model = load_model()
    results: list[dict] = []
    for pair in symbols:
        symbol = pair.replace("USDT", "")
        try:
            price = get_symbol_price(symbol)
            klines = get_klines(symbol)
            if not klines:
                continue
            closes = [float(k[4]) for k in klines]
            tp, sl = dynamic_tp_sl(closes, price)
            feature_vector, _, _ = generate_features(symbol)
            prob_up = predict_prob_up(model, feature_vector) if model else 0.5
            expected_profit = calculate_expected_profit(price, tp, 10, sl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skip %s: %s", symbol, exc)
            continue

        if expected_profit > 0.005 and prob_up > 0.5:
            results.append(
                {
                    "symbol": symbol,
                    "expected_profit": expected_profit,
                    "prob_up": prob_up,
                }
            )

    return results

if __name__ == "__main__":
    import asyncio
    import os
    import sys
    from telegram import Bot

    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHAT_ID = os.getenv("CHAT_ID")

    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        candidates = demo_candidates_loop(symbols)
        for c in candidates:
            print(f"{c['symbol']}: prob_up={c['prob_up']:.2f}, expected={c['expected_profit']}")
        sys.exit(0)

    if TELEGRAM_TOKEN and CHAT_ID:
        bot = Bot(token=TELEGRAM_TOKEN)
        asyncio.run(daily_analysis_task(bot, int(CHAT_ID)))
    else:
        print("❌ TELEGRAM_TOKEN або CHAT_ID не встановлено")
