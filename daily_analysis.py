# ✅ Еталонна логіка GPT-звіту /zarobyty (v2.0) — повна реалізація
# Мета: максимізувати прибуток за добу, діючи в рамках поточного балансу Binance

import datetime
import asyncio
import pytz
import statistics
import logging
import os
import numpy as np

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
    get_usdt_balance,
    get_token_balance,
    is_symbol_valid,
    get_valid_usdt_symbols,
    VALID_PAIRS,
    refresh_valid_pairs,
)
from binance_api import get_candlestick_klines
from config import MIN_PROB_UP, MIN_EXPECTED_PROFIT, MIN_TRADE_AMOUNT, TRADE_LOOP_INTERVAL
from gpt_utils import ask_gpt
from utils import (
    convert_to_uah,
    calculate_rr,
    calculate_expected_profit,
    calculate_indicators,
    kelly_fraction,
    dynamic_tp_sl,
    advanced_buy_filter,
    estimate_profit_debug,
    log_trade,
    get_sector,
    analyze_btc_correlation,
    _ema,
)
from history import _load_history, get_failed_tokens_history, add_trade
from coingecko_api import get_sentiment
from ml_model import (
    load_model,
    generate_features,
    predict_direction,
    predict_prob_up,
)
from telegram import Bot

symbols = get_valid_usdt_symbols()

logger = logging.getLogger(__name__)

# Global minimum thresholds (override via config)
MIN_VOLUME = 100_000


async def get_trading_symbols() -> list[str]:
    """Return list of trading symbols available for analysis."""
    return get_valid_usdt_symbols()

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
        result = update_tp_sl_order(symbol, new_tp, new_sl)
        if result:
            log_tp_sl_change(symbol, "updated", new_tp, new_sl)
            from telegram_bot import bot, ADMIN_CHAT_ID
            asyncio.create_task(
                bot.send_message(
                    ADMIN_CHAT_ID,
                    f"\u267B\ufe0f TP/SL оновлено для {symbol}: TP={new_tp}, SL={new_sl}",
                )
            )
            return True
    return False


def execute_buy_order(symbol: str, amount_usdt: float):
    try:
        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        price = get_symbol_price(pair)
        if price is None:
            logger.warning("Price unavailable for %s", symbol)
            return
        quantity = round(amount_usdt / price, 5)
        buy_order = place_market_order(pair, "BUY", amount_usdt)
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

        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        price = token.get("price") or get_symbol_price(pair)
        if price is None:
            continue
        klines = get_klines(pair)
        if not klines:
            continue
        indicators = calculate_indicators(klines)
        rr = token.get("risk_reward")
        if rr is None:
            rr = calculate_rr(klines)

        closes = [float(k[4]) for k in klines]
        tp_def, sl_def = dynamic_tp_sl(closes, price)

        enriched.append(
            {
                "symbol": pair,
                "price": price,
                "risk_reward": rr,
                "tp_price": token.get("tp_price") or tp_def,
                "sl_price": token.get("sl_price") or sl_def,
                "momentum": token.get("momentum", indicators.get("momentum", 0)),
                "indicators": indicators,
                "sector_score": token.get("sector_score", 0),
                "success_score": get_success_score(symbol),
                "orderbook_bias": token.get("orderbook_bias", 0),
                "btc_corr": token.get("btc_corr") if "btc_corr" in token else analyze_btc_correlation(pair),
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

def generate_zarobyty_report() -> tuple[str, list, list, str]:
    balances = get_binance_balances()
    usdt_balance = balances.get("USDT", 0) or 0
    now = datetime.datetime.now(pytz.timezone("Europe/Kyiv"))
    token_data = []

    if len(VALID_PAIRS) < 50:
        logger.warning(
            "⚠️ VALID_PAIRS містить лише %d символів — можливі помилки",
            len(VALID_PAIRS),
        )

    for symbol, amount in balances.items():
        if symbol == "USDT" or amount == 0:
            continue
        if symbol not in load_tradable_usdt_symbols():
            continue

        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"

        price = get_symbol_price(pair)
        if price is None:
            continue
        uah_value = convert_to_uah(price * amount)
        klines = get_klines(pair)
        if not klines:
            continue
        trades = get_my_trades(pair)
        indicators = calculate_indicators(klines)
        average_buy_price = sum([float(t['price']) * float(t['qty']) for t in trades]) / sum([float(t['qty']) for t in trades]) if trades else price
        pnl_percent = ((price - average_buy_price) / average_buy_price) * 100
        rr = calculate_rr(klines)
        volume_24h = sum(float(k[5]) for k in get_price_history(pair)) if klines else 0
        sector = get_sector(symbol)
        btc_corr = analyze_btc_correlation(pair)

        token_data.append({
            "symbol": pair,
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
    sell_recommendations = [t for t in token_data if t["pnl"] >= 0.0]
    sell_symbols = {t["symbol"] for t in sell_recommendations}
    exchange_rate_uah = get_usdt_to_uah_rate()
    usdt_from_sales = sum([t["uah_value"] for t in sell_recommendations]) / exchange_rate_uah
    available_usdt = round(usdt_balance + usdt_from_sales, 2)

    # 🔍 Candidates to analyze
    symbols_from_balance = set(t['symbol'].upper() for t in token_data)
    market_symbols = set(t["symbol"].upper() for t in get_top_tokens(limit=50))

    valid_symbols = get_valid_usdt_symbols()
    logger.debug(
        "Valid symbols: %s examples: %s",
        len(valid_symbols),
        valid_symbols[:10],
    )
    symbols_to_analyze: list[str] = []
    success = 0
    fail = 0
    for sym in symbols:
        pair = sym if sym.endswith("USDT") else f"{sym}USDT"
        if is_symbol_valid(pair):
            symbols_to_analyze.append(pair)
            success += 1
        else:
            logger.info(
                "⏭️ Пропущено %s: не торгується. valid_symbols=%s",
                pair,
                valid_symbols,
            )
            fail += 1
    logger.debug("Symbols to analyze: %d success, %d skipped", success, fail)

    enriched_tokens: list[dict] = []
    buy_candidates: list[dict] = []
    model = load_model()
    if not model:
        logger.warning("\u26A0\ufe0f Модель недоступна")

    for symbol in symbols_to_analyze:
        try:
            feature_vector, _, _ = generate_features(symbol)
            fv = np.asarray(feature_vector).reshape(1, -1)
            prob_up = predict_prob_up(model, fv) if model else 0.5
            expected_profit = estimate_profit_debug(symbol)
            print(f"\U0001F4CA {symbol}: prob_up={prob_up:.2f}, expected_profit={expected_profit}")

            enriched_tokens.append(
                {
                    "symbol": symbol,
                    "expected_profit": expected_profit,
                    "prob_up": prob_up,
                    "score": prob_up * expected_profit,
                }
            )

            if prob_up >= MIN_PROB_UP and expected_profit >= MIN_EXPECTED_PROFIT:
                buy_candidates.append(
                    {
                        "symbol": symbol,
                        "expected_profit": expected_profit,
                        "prob_up": prob_up,
                        "score": prob_up * expected_profit,
                    }
                )
        except Exception as e:
            logger.warning(f"⚠️ Пропущено {symbol}: {str(e)}")
            continue

    buy_candidates.sort(key=lambda x: x["score"], reverse=True)

    # Якщо немає сильних кандидатів — fallback до найкращого доступного
    if not buy_candidates and enriched_tokens:
        enriched_tokens.sort(key=lambda x: x["score"], reverse=True)
        fallback = enriched_tokens[0]
        print(
            f"\u26A0\ufe0f No candidates passed filters, forcing fallback: {fallback['symbol']}"
        )
        buy_candidates.append(fallback)  # Додаємо, навіть якщо не проходить фільтр

    # 🟢 Сортуємо й обираємо токени на купівлю (TOP 3)
    buy_plan = sorted(buy_candidates, key=lambda x: x["score"], reverse=True)[:3]
    candidate_lines = [t["symbol"] for t in buy_plan[:3]]

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
    return report, sell_recommendations, buy_plan, ""




def generate_daily_stats_report() -> str:
    """Temporary stub for daily stats command."""
    return "\u23F3 \u041F\u043E\u043A\u0438 \u0449\u043E \u0449\u043E\u0434\u0435\u043D\u043D\u0438\u0439 \u0437\u0432\u0456\u0442 \u043D\u0435 \u0440\u0435\u0430\u043B\u0456\u0437\u043E\u0432\u0430\u043D\u043E."


async def daily_analysis_task(bot: Bot, chat_id: int) -> None:
    """Run daily analysis and notify about TP/SL updates."""
    print("\U0001F680 Start daily_analysis_task")

    try:
        symbols = await get_trading_symbols()
        print(f"\U0001F4E6 Trading symbols loaded: {len(symbols)}")
        print(f"\U0001F539 Example symbols: {symbols[:5]}")
    except Exception as e:  # noqa: BLE001
        print(f"\u274C Failed to get trading symbols: {e}")
        return

    for symbol in symbols:
        print(f"\U0001F50D Analyzing {symbol}")

    report, _, _, gpt_text = generate_zarobyty_report()
    full_text = f"{report}\n\n{gpt_text}"
    await send_message_parts(bot, chat_id, full_text)


async def send_zarobyty_forecast(bot, chat_id: int) -> None:
    """Send the GPT forecast separately, splitting long text into chunks."""
    _, _, _, gpt_text = generate_zarobyty_report()
    for part in split_telegram_message(gpt_text, 4000):
        await bot.send_message(chat_id, part)


async def auto_trade_loop():
    """Continuous auto-trading loop with dynamic interval."""

    valid_pairs = get_valid_usdt_symbols()

    while True:
        try:
            _, sell_recommendations, buy_candidates, _ = generate_zarobyty_report()
            print(f"🧾 SELL candidates: {len(sell_recommendations)}")
            print(f"🧾 BUY candidates: {len(buy_candidates)}")

            for token in sell_recommendations:
                symbol = token["symbol"]
                pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
                quantity = token.get("quantity") or token.get("amount")
                if not quantity:
                    try:
                        price = get_symbol_price(pair)
                        bal = get_token_balance(symbol.replace("USDT", ""))
                        if bal and price:
                            quantity = bal
                        elif token.get("balance"):
                            quantity = float(token["balance"]) / price if price else 0
                    except Exception as exc:  # pragma: no cover - network errors
                        logger.warning("Balance check failed for %s: %s", symbol, exc)
                        quantity = 0
                try:
                    place_market_order(pair, "SELL", quantity)
                    price = get_symbol_price(pair)
                    if price is not None:
                        log_trade("SELL", pair, quantity, price)
                        add_trade(pair, "SELL", quantity, price)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Auto-sell error for %s: %s", symbol, exc)
                    from telegram_bot import bot, ADMIN_CHAT_ID
                    await bot.send_message(ADMIN_CHAT_ID, f"\u26A0\ufe0f Sell error {symbol}: {exc}")

            if buy_candidates:
                balance = get_usdt_balance()
                if not balance:
                    logger.warning("USDT balance unavailable for buying")
                    from telegram_bot import bot, ADMIN_CHAT_ID
                    await bot.send_message(ADMIN_CHAT_ID, "\u26A0\ufe0f Немає USDT для покупки")
                    await asyncio.sleep(TRADE_LOOP_INTERVAL)
                    continue
                for candidate in buy_candidates:
                    pair = candidate["symbol"].upper()
                    if pair not in valid_pairs:
                        continue
                    price = get_symbol_price(candidate["symbol"])
                    if price is None or price <= 0:
                        continue

                    win_loss_ratio = 2.0
                    fraction = kelly_fraction(candidate.get("prob_up", 0.5), win_loss_ratio)
                    amount_usdt = max(MIN_TRADE_AMOUNT, balance * fraction)
                    amount_usdt = min(amount_usdt, balance)

                    if amount_usdt < MIN_TRADE_AMOUNT:
                        continue
                    try:
                        order = place_market_order(candidate["symbol"], "BUY", amount_usdt)
                        qty = amount_usdt / price
                        if isinstance(order, dict):
                            qty = float(order.get("executedQty", qty))
                        log_trade("BUY", candidate["symbol"], qty, price)
                        add_trade(candidate["symbol"], "BUY", qty, price)

                        klines = get_klines(candidate["symbol"])
                        closes = [float(k[4]) for k in klines]
                        tp, sl = dynamic_tp_sl(closes, price)
                        orders = get_open_orders(pair)
                        has_tp = any(o.get("type") == "LIMIT" for o in orders)
                        has_sl = any(o.get("type") == "STOP_LOSS_LIMIT" for o in orders)
                        if not (has_tp and has_sl):
                            result = update_tp_sl_order(candidate["symbol"], tp, sl)
                            if result:
                                from telegram_bot import bot, ADMIN_CHAT_ID
                                await bot.send_message(
                                    ADMIN_CHAT_ID,
                                    f"\u267B\ufe0f TP/SL встановлено для {candidate['symbol']}: TP={tp}, SL={sl}",
                                )
                        break
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Auto-buy error for %s: %s", pair, exc)
                        from telegram_bot import bot, ADMIN_CHAT_ID
                        await bot.send_message(ADMIN_CHAT_ID, f"\u26A0\ufe0f Buy error {pair}: {exc}")
                        continue

        except Exception as e:  # noqa: BLE001
            logger.exception("Auto-trade error: %s", e)
            from telegram_bot import bot, ADMIN_CHAT_ID
            await bot.send_message(ADMIN_CHAT_ID, str(e))

        await asyncio.sleep(TRADE_LOOP_INTERVAL)

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
        pair = pair.upper()
        if not pair.endswith("USDT"):
            pair = f"{pair}USDT"
        symbol = pair
        try:
            price = get_symbol_price(pair)
            if price is None:
                continue
            klines = get_klines(pair)
            if not klines:
                continue
            closes = [float(k[4]) for k in klines]
            tp, sl = dynamic_tp_sl(closes, price)
            feature_vector, _, _ = generate_features(pair)
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
        asyncio.run(auto_trade_loop())
    else:
        print("❌ TELEGRAM_TOKEN або CHAT_ID не встановлено")
