# ✅ Еталонна логіка GPT-звіту /zarobyty (v2.0) — повна реалізація
# Мета: максимізувати прибуток за добу, діючи в рамках поточного балансу Binance

import datetime
import asyncio
import json
import pytz
import statistics
import logging
import numpy as np
import math

# Lookback window for trade history metrics
lookback_days = 30

from binance_api import (
    get_binance_balances,
    get_symbol_price,
    get_candlestick_klines as get_price_history,
    get_candlestick_klines as get_klines,
    get_recent_trades as get_my_trades,
    get_top_tokens,
    get_top_symbols_by_volume,
    load_tradable_usdt_symbols,
    get_usdt_to_uah_rate,
    place_market_order,
    place_limit_sell_order,
    get_open_orders,
    update_tp_sl_order,
    log_tp_sl_change,
    notify_telegram,
    get_usdt_balance,
    get_token_balance,
    market_sell,
    get_lot_step,
    is_symbol_valid,
    get_valid_usdt_symbols,
    get_all_valid_symbols,
    refresh_valid_pairs,
)
from binance_api import get_candlestick_klines
from config import (
    MIN_PROB_UP,
    MIN_EXPECTED_PROFIT,
    MIN_TRADE_AMOUNT,
    TRADE_LOOP_INTERVAL,
    MAX_AUTO_TRADE_ITERATIONS,
    OPENAI_API_KEY,
)
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
from services.telegram_service import send_messages
from history import _load_history, get_failed_tokens_history, add_trade
from coingecko_api import get_sentiment
from ml_model import (
    load_model,
    generate_features,
    predict_direction,
    predict_prob_up,
)
from telegram import Bot

import time

# Новий список топ-60 символів для аналізу
TRADING_SYMBOLS = get_top_symbols_by_volume(limit=60)
VALID_PAIRS = get_all_valid_symbols()

logger = logging.getLogger(__name__)

# Global minimum thresholds (override via config)
MIN_VOLUME = 100_000

# Path to store timestamp of the last USDT balance warning
NO_USDT_ALERT_FILE = "no_usdt_alert.txt"

# Minimum interval between "no USDT" warnings (in seconds)
NO_USDT_ALERT_INTERVAL = 10800


def log_and_telegram(message: str) -> None:
    """Log ``message`` and send it to Telegram."""

    logger.warning(message)
    try:
        notify_telegram(message)
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.warning("[dev] Failed to notify Telegram: %s", exc)


async def get_trading_symbols() -> list[str]:
    """Return list of trading symbols available for analysis."""
    return TRADING_SYMBOLS


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
                    f"\u267b\ufe0f TP/SL оновлено для {symbol}: TP={new_tp}, SL={new_sl}",
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

        tp_order = place_limit_sell_order(
            f"{symbol.upper()}USDT", quantity, take_profit_price
        )
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
                "btc_corr": (
                    token.get("btc_corr")
                    if "btc_corr" in token
                    else analyze_btc_correlation(pair)
                ),
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


def calculate_adaptive_filters(days: int = lookback_days) -> tuple[float, float]:
    """Return adaptive min_expected_profit and min_prob_up for the last ``days`` trades."""

    history = _load_history()
    if not history:
        return MIN_EXPECTED_PROFIT, MIN_PROB_UP

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    recent = [h for h in history if datetime.datetime.fromisoformat(h.get("timestamp", "1970-01-01")) >= cutoff]

    successful = [
        h
        for h in recent
        if h.get("take_profit_hit") is True or float(h.get("sell_profit", 0)) > 0
    ]

    if not successful:
        return MIN_EXPECTED_PROFIT, MIN_PROB_UP

    exp_profits = [float(h.get("expected_profit", 0)) for h in successful]
    probs = [float(h.get("prob_up", 0.5)) for h in successful]

    mean_expected_profit_success = statistics.mean(exp_profits)
    mean_prob_up_success = statistics.mean(probs)

    adaptive_min_profit = round(mean_expected_profit_success * 0.7, 4)
    adaptive_min_prob = round(mean_prob_up_success * 0.9, 4)

    return adaptive_min_profit, adaptive_min_prob


async def generate_zarobyty_report() -> tuple[str, list, list, dict | None, dict]:
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
        average_buy_price = (
            sum([float(t["price"]) * float(t["qty"]) for t in trades])
            / sum([float(t["qty"]) for t in trades])
            if trades
            else price
        )
        pnl_percent = ((price - average_buy_price) / average_buy_price) * 100
        rr = calculate_rr(klines)
        volume_24h = sum(float(k[5]) for k in get_price_history(pair)) if klines else 0
        sector = get_sector(symbol)
        btc_corr = analyze_btc_correlation(pair)

        token_data.append(
            {
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
                "btc_corr": btc_corr,
            }
        )

    # 🔻 Sell recommendations
    sell_recommendations = [t for t in token_data if t["pnl"] >= 0.0]
    sell_symbols = {t["symbol"] for t in sell_recommendations}
    exchange_rate_uah = get_usdt_to_uah_rate()
    usdt_from_sales = (
        sum([t["uah_value"] for t in sell_recommendations]) / exchange_rate_uah
    )
    available_usdt = round(usdt_balance + usdt_from_sales, 2)

    # 🔍 Candidates to analyze
    symbols_from_balance = set(t["symbol"].upper() for t in token_data)
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
    for sym in TRADING_SYMBOLS:
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

    symbols_for_analysis = symbols_to_analyze
    symbols_for_analysis = symbols_for_analysis[:60]

    enriched_tokens: list[dict] = []
    buy_candidates: list[dict] = []
    model = load_model()
    if not model:
        logger.warning("\u26a0\ufe0f Модель недоступна")

    for symbol in symbols_for_analysis:
        try:
            feature_vector, _, _ = generate_features(symbol)
            fv = np.asarray(feature_vector).reshape(1, -1)
            prob_up = predict_prob_up(model, fv) if model else 0.5
            expected_profit = estimate_profit_debug(symbol)
            logger.info(
                f"[dev] \U0001f4ca {symbol}: prob_up={prob_up:.2f}, expected_profit={expected_profit:.4f}"
            )

            enriched_tokens.append(
                {
                    "symbol": symbol,
                    "expected_profit": expected_profit,
                    "prob_up": prob_up,
                    "score": prob_up * expected_profit,
                }
            )

            if prob_up >= MIN_PROB_UP:
                if expected_profit < MIN_EXPECTED_PROFIT:
                    logger.info(
                        "\u26a0\ufe0f Low expected profit for %s: %.4f USDT",
                        symbol,
                        expected_profit,
                    )
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
        logger.info(
            "\u26a0\ufe0f No candidates passed filters, forcing fallback: %s",
            fallback["symbol"],
        )
        buy_candidates.append(fallback)  # Додаємо, навіть якщо не проходить фільтр

    # 🟢 Сортуємо й обираємо токени на купівлю (TOP 3)
    buy_plan = sorted(buy_candidates, key=lambda x: x["score"], reverse=True)[:3]
    candidate_lines = [t["symbol"] for t in buy_plan[:3]]

    # 📝 Final report
    report_lines = []
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    report_lines.append(f"🕒 Звіт сформовано: {timestamp}  ")
    report_lines.append("💰 Баланс:  ")

    balance_parts = []
    for t in token_data:
        balance_parts.append(
            f"{t['symbol']}: {t['amount']:.4f} ≈ ~{t['uah_value']:.2f}₴"
        )
    balance_parts.append(
        f"USDT: {usdt_balance:.4f} ≈ ~{convert_to_uah(usdt_balance):.2f}₴"
    )
    report_lines.extend(balance_parts)
    total_uah = round(
        sum([t["uah_value"] for t in token_data]) + convert_to_uah(usdt_balance),
        2,
    )
    report_lines.append(f"Загальний баланс: {total_uah:.2f}₴  \n")
    report_lines.append("⸻  ")

    balance_str = ", ".join(balance_parts)

    report_lines.append("📉 Що продаємо:  ")
    sell_lines = []
    for t in sell_recommendations:
        received = t["amount"] * t["price"]
        reason = f"прибуток {t['pnl']:.2f}%"
        sell_lines.append(
            f"{t['symbol']} {t['amount']:.4f} ({reason}) → {received:.2f} USDT"
        )
    if not sell_lines:
        sell_lines.append("(порожньо)")
    report_lines.extend(sell_lines)
    report_lines.append("\n⸻  ")

    report_lines.append("♻️ Що сконвертовано:  ")
    convert_lines: list[str] = []
    if not convert_lines:
        convert_lines.append("(порожньо)")
    report_lines.extend(convert_lines)
    report_lines.append("\n⸻  ")

    report_lines.append("📈 Що купуємо:  ")
    buy_lines = []
    for t in buy_plan:
        reason = f"exp={t['expected_profit']:.2f}, prob={t['prob_up']:.2f}"
        buy_lines.append(f"{t['symbol']} ({reason})")
    if not buy_lines:
        buy_lines.append("(порожньо)")
    report_lines.extend(buy_lines)
    report_lines.append("\n⸻  ")

    total_expected_profit = sum(t.get("expected_profit", 0) for t in buy_plan)
    expected_profit_usdt = round(total_expected_profit, 2)
    expected_profit_uah = convert_to_uah(expected_profit_usdt)
    report_lines.append(
        f"💹 Очікуваний прибуток: {expected_profit_usdt:.2f} USDT ≈ {expected_profit_uah:.2f}₴ за 24г"
    )

    scoreboard = [
        f"{t['symbol']}: score={t['score']:.4f}"
        for t in sorted(enriched_tokens, key=lambda x: x['score'], reverse=True)[:3]
    ]

    report = "\n".join(report_lines)

    adaptive_min_profit, adaptive_min_prob = calculate_adaptive_filters()
    adaptive_filters = {
        "min_expected_profit": adaptive_min_profit,
        "min_prob_up": adaptive_min_prob,
    }

    balance_dict = {k: v for k, v in balances.items() if v}
    predictions = {
        t["symbol"]: {
            "expected_profit": t["expected_profit"],
            "prob_up": t["prob_up"],
            "score": t["score"],
        }
        for t in enriched_tokens
    }

    summary = {
        "balance": balance_dict,
        "sell": [s.replace("USDT", "") for s in sell_symbols],
        "buy": [c.replace("USDT", "") for c in candidate_lines],
        "total_profit": str(expected_profit_usdt),
        "market_trend": get_sentiment(),
        "filters": {
            "min_score": 0.3,
            "min_expected_profit": 0.2,
            "min_prob_up": 0.45,
            "min_volatility": 1.0,
            "min_volume": 10_000_000,
            "adaptive_min_expected_profit": adaptive_min_profit,
            "adaptive_min_prob_up": adaptive_min_prob,
        },
        "token_scores": predictions,
    }
    gpt_result = await ask_gpt(summary, OPENAI_API_KEY)
    import json

    try:
        gpt_result = json.loads(gpt_result)
    except Exception:
        logger.warning("[dev] ❌ Неможливо розпарсити GPT відповідь як JSON")
        gpt_result = {}
    if gpt_result == {}:
        log_and_telegram("[GPT] ⚠️ Порожній прогноз, можливо, сталася помилка")
    if gpt_result:
        forecast = {
            "recommend_buy": gpt_result.get("buy", []),
            "do_not_buy": gpt_result.get("sell", []),
        }
        with open("gpt_forecast.txt", "w", encoding="utf-8") as f:
            json.dump(forecast, f, indent=2, ensure_ascii=False)
        logger.info("GPT forecast saved to gpt_forecast.txt")
    else:
        logger.warning("[dev] ❌ GPT result is empty or invalid.")
        forecast = gpt_result

    if not buy_plan and buy_candidates:
        logger.info("⚠️ GPT filter empty — using top buy candidates")
        logger.info("⚠️ GPT не рекомендував жоден токен — використано buy_candidates як fallback")
        buy_plan = sorted(buy_candidates, key=lambda x: x["score"], reverse=True)[:3]

    if not buy_plan and forecast and forecast.get("recommend_buy"):
        fallback_tokens = forecast["recommend_buy"]
        logger.info(
            "⚠️ GPT BUY fallback enabled — using tokens from GPT: %s", fallback_tokens
        )
        for sym in fallback_tokens:
            buy_plan.append({"symbol": sym + "USDT"})

    return report, sell_recommendations, buy_plan, forecast, predictions


def generate_daily_stats_report() -> str:
    """Temporary stub for daily stats command."""
    return "\u23f3 \u041f\u043e\u043a\u0438 \u0449\u043e \u0449\u043e\u0434\u0435\u043d\u043d\u0438\u0439 \u0437\u0432\u0456\u0442 \u043d\u0435 \u0440\u0435\u0430\u043b\u0456\u0437\u043e\u0432\u0430\u043d\u043e."


async def daily_analysis_task(bot: Bot, chat_id: int) -> None:
    """Run daily analysis and notify about TP/SL updates."""
    logger.info("\U0001f680 Start daily_analysis_task")

    try:
        symbols = await get_trading_symbols()
        logger.info("\U0001f4e6 Trading symbols loaded: %d", len(symbols))
        logger.info("\U0001f539 Example symbols: %s", symbols[:5])
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to get trading symbols: %s", e)
        return

    for symbol in symbols:
        logger.info("\U0001f50d Analyzing %s", symbol)

    report, _, _, forecast, predictions = await generate_zarobyty_report()
    if predictions:
        from gpt_utils import save_predictions
        save_predictions(predictions)
    else:
        logger.warning(
            "[dev] ❌ Аналіз не згенерував predictions, нічого не збережено."
        )

    await send_message_parts(bot, chat_id, report)
    if forecast is not None:
        summary_lines = []
        if forecast.get("recommend_buy"):
            summary_lines.append("🤖 BUY: " + ", ".join(forecast["recommend_buy"]))
        if forecast.get("do_not_buy"):
            summary_lines.append("🤖 SELL: " + ", ".join(forecast["do_not_buy"]))
        if summary_lines:
            await bot.send_message(chat_id, "\n".join(summary_lines))


async def send_zarobyty_forecast(bot, chat_id: int) -> None:
    """Send summarized GPT forecast."""
    _, _, _, forecast, _ = await generate_zarobyty_report()
    if forecast is None:
        await bot.send_message(chat_id, "GPT forecast unavailable")
        return
    lines = []
    if forecast.get("recommend_buy"):
        lines.append("🤖 BUY: " + ", ".join(forecast["recommend_buy"]))
    if forecast.get("do_not_buy"):
        lines.append("🤖 SELL: " + ", ".join(forecast["do_not_buy"]))
    if lines:
        await bot.send_message(chat_id, "\n".join(lines))


async def auto_trade_loop(max_iterations: int = MAX_AUTO_TRADE_ITERATIONS) -> None:
    """Continuous auto-trading loop with dynamic interval."""

    valid_pairs = get_valid_usdt_symbols()
    iteration = 0

    while iteration < max_iterations:
        try:
            _, sell_recommendations, buy_candidates, _, _ = await generate_zarobyty_report()
            logger.info("🧾 SELL candidates: %d", len(sell_recommendations))
            logger.info("🧾 BUY candidates: %d", len(buy_candidates))

            sold_any = False

            for token in sell_recommendations:
                symbol = token["symbol"]
                amount = (
                    token.get("balance")
                    or token.get("amount")
                    or token.get("quantity", 0)
                )
                if amount and amount > 0:
                    try:
                        step = get_lot_step(symbol)
                        adjusted_amount = math.floor(amount / step) * step
                        result = market_sell(symbol, adjusted_amount)
                        logger.info("✅ Продано %s: %s | %s", symbol, amount, result)
                        if result.get("status") == "success":
                            sold_any = True
                    except Exception as e:  # noqa: BLE001
                        logger.error("❌ Sell error for %s: %s", symbol, e)

            await asyncio.sleep(2)
            balance = get_usdt_balance()

            if buy_candidates:
                if not balance:
                    logger.warning("USDT balance unavailable for buying")
                    try:
                        with open(NO_USDT_ALERT_FILE, "r") as f:
                            last_alert_time = float(f.read().strip())
                    except (FileNotFoundError, ValueError):
                        last_alert_time = 0

                    now = time.time()
                    if (now - last_alert_time > NO_USDT_ALERT_INTERVAL) and not sold_any:
                        from telegram_bot import ADMIN_CHAT_ID
                        from auto_trade_cycle import generate_conversion_signals

                        _, _, _, _, _, _, _ = generate_conversion_signals()
                        # 🔕 [dev] Повідомлення про відсутність USDT більше не надсилається
                        # if usdt_balance < MIN_TRADE_AMOUNT:
                        #     send_telegram_message("⚠️ Немає USDT для покупки.\n")
                        with open(NO_USDT_ALERT_FILE, "w") as f:
                            f.write(str(now))

                    await asyncio.sleep(TRADE_LOOP_INTERVAL)
                    iteration += 1
                    continue
                for candidate in buy_candidates:
                    pair = candidate["symbol"].upper()
                    if pair not in valid_pairs:
                        continue
                    price = get_symbol_price(candidate["symbol"])
                    if price is None or price <= 0:
                        continue

                    win_loss_ratio = 2.0
                    fraction = kelly_fraction(
                        candidate.get("prob_up", 0.5), win_loss_ratio
                    )
                    amount_usdt = max(MIN_TRADE_AMOUNT, balance * fraction)
                    amount_usdt = min(amount_usdt, balance)

                    if amount_usdt < MIN_TRADE_AMOUNT:
                        continue
                    try:
                        order = place_market_order(
                            candidate["symbol"], "BUY", amount_usdt
                        )
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
                                    f"\u267b\ufe0f TP/SL встановлено для {candidate['symbol']}: TP={tp}, SL={sl}",
                                )
                        break
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Auto-buy error for %s: %s", pair, exc)
                        from telegram_bot import bot, ADMIN_CHAT_ID

                        await bot.send_message(
                            ADMIN_CHAT_ID, f"\u26a0\ufe0f Buy error {pair}: {exc}"
                        )
                        continue

        except Exception as e:  # noqa: BLE001
            logger.exception("Auto-trade error: %s", e)
            from telegram_bot import bot, ADMIN_CHAT_ID

            await bot.send_message(ADMIN_CHAT_ID, str(e))

        await asyncio.sleep(TRADE_LOOP_INTERVAL)
        iteration += 1


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

    return rsi < 40 and macd_cross and bb_touch and momentum > 0 and rr > 1.5


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
        if (
            missing
            or "indicators" not in token
            or "rsi" not in token.get("indicators", {})
        ):
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
    raise RuntimeError("🚫 Запускати тільки через systemd або run_auto_trade.py")
