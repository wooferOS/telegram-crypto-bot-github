# ✅ Еталонна логіка GPT-звіту /zarobyty (v2.0) — повна реалізація
# Мета: максимізувати прибуток за добу, діючи в рамках поточного балансу Binance

import datetime
import pytz
import statistics
import logging

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
    calculate_indicators,
    get_sector,
    analyze_btc_correlation,
    _ema,
)
from history import _load_history
from coingecko_api import get_sentiment
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

async def send_message_parts(bot, chat_id: int, text: str) -> None:
    """Send text to Telegram in chunks not exceeding 4096 characters."""
    MAX_LENGTH = 4096
    for i in range(0, len(text), MAX_LENGTH):
        await bot.send_message(chat_id, text[i:i + MAX_LENGTH])



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
    success_rate: float = 0.65,
    fee: float = 0.001,
) -> float:
    """Return expected profit adjusted for fees and success probability."""

    if price <= 0 or tp_price <= price:
        return 0.0
    gross_profit = (tp_price - price) * amount / price
    net_profit = gross_profit * (1 - 2 * fee)
    adjusted_profit = net_profit * success_rate
    if sl_price and sl_price < price:
        risk_loss = (price - sl_price) * amount / price
        expected_loss = risk_loss * (1 - success_rate)
        return round(adjusted_profit - expected_loss, 2)
    return round(adjusted_profit, 2)


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
    """Return daily profit report text, keyboard and updates.

    Steps:
    1. Calculate current balance in UAH and USDT.
    2. Identify sell candidates where PnL >= 1%%.
    3. Pick buy candidates with ``rsi < 40`` and ``risk_reward > 1.5``.
       Remove any symbols that are also scheduled for selling.
    4. Sum ``expected_profit`` from buy candidates (0 if missing).
    5. Send all data to GPT together with market trend and active strategy.
    """
    balances = get_binance_balances()
    usdt_balance = balances.get("USDT", 0)
    if usdt_balance is None:
        usdt_balance = 0

    token_data = []
    now = datetime.datetime.now(pytz.timezone("Europe/Kyiv"))

    for symbol, amount in balances.items():
        if symbol == "USDT" or amount == 0:
            continue
        if symbol not in load_tradable_usdt_symbols():
            continue

        price = get_symbol_price(symbol)
        uah_value = convert_to_uah(price * amount)
        price_history = get_price_history(symbol)
        klines = get_klines(symbol)
        trades = get_my_trades(f"{symbol}USDT")

        indicators = calculate_indicators(klines)
        average_buy_price = sum([float(t['price']) * float(t['qty']) for t in trades]) / sum([float(t['qty']) for t in trades]) if trades else price
        pnl_percent = ((price - average_buy_price) / average_buy_price) * 100
        rr = calculate_rr(klines)
        volume_24h = 0
        if (
            isinstance(price_history, list)
            and len(price_history) > 0
            and isinstance(price_history[0], (list, tuple))
        ):
            volume_24h = sum(float(k[5]) for k in price_history if len(k) > 5)
        sector = get_sector(symbol)
        btc_corr = analyze_btc_correlation(symbol)

        momentum = indicators.get("EMA_8", 0) - indicators.get("EMA_13", 0)
        sector_score = 0
        orderbook_bias = 0
        success_score = get_success_score(symbol)

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

    # Sell tokens with profit >= 1%%
    sell_recommendations = [t for t in token_data if t["pnl"] >= 1.0]
    sell_symbols = {t["symbol"] for t in sell_recommendations}

    exchange_rate_uah = get_usdt_to_uah_rate()
    usdt_from_sales = sum([t["uah_value"] for t in sell_recommendations]) / exchange_rate_uah
    available_usdt = round(usdt_balance + usdt_from_sales, 2)

    symbols_from_balance = set(t['symbol'].upper() for t in token_data)
    market_symbols = set(t["symbol"].upper() for t in get_top_tokens(limit=50))
    symbols_to_analyze = symbols_from_balance.union(market_symbols)

    tradable_symbols = set(s.upper() for s in load_tradable_usdt_symbols())
    symbols_to_analyze = [s for s in symbols_to_analyze if s in tradable_symbols]

    enriched_tokens = []
    for symbol in symbols_to_analyze:
        price = get_symbol_price(symbol)
        klines = get_klines(symbol)
        indicators = calculate_indicators(klines)
        rr = calculate_rr(klines)
        sector = get_sector(symbol)
        price_stats = get_price_history(symbol)
        volume_24h = 0
        if (
            isinstance(price_stats, list)
            and len(price_stats) > 0
            and isinstance(price_stats[0], (list, tuple))
        ):
            volume_24h = sum(float(k[5]) for k in price_stats if len(k) > 5)
        volumes = [float(k[5]) for k in klines]
        avg_volume = statistics.fmean(volumes[-20:]) if volumes else 0
        volume_change = volume_24h - avg_volume
        btc_corr = analyze_btc_correlation(symbol)

        closes = [float(k[4]) for k in klines]
        ema8_series = _ema(closes, 8) if len(closes) >= 8 else [0] * len(closes)
        ema_cross = False
        if len(closes) >= 9:
            ema_cross = closes[-2] < ema8_series[-2] and closes[-1] > ema8_series[-1]

        klines_7d = get_candlestick_klines(symbol, interval="1d", limit=7)
        closes_7d = [float(k[4]) for k in klines_7d]
        if len(closes_7d) > 1:
            mean_price = statistics.fmean(closes_7d)
            variance = statistics.pvariance(closes_7d)
            volatility_7d = (variance ** 0.5) / mean_price * 100
        else:
            volatility_7d = 0

        enriched_tokens.append(
            {
                "symbol": symbol,
                "price": price,
                "risk_reward": rr,
                "sector": sector,
                "btc_corr": btc_corr,
                "volume_change_24h": volume_change,
                "volatility_7d": volatility_7d,
                "ema_cross": ema_cross,
                "momentum": momentum,
                "sector_score": sector_score,
                "orderbook_bias": orderbook_bias,
                "success_score": success_score,
                "indicators": {
                    "rsi": indicators["RSI"],
                    "ema8": indicators.get("EMA_8", 0),
                },
            }
        )

    # Debug: show top tokens before applying filters
    preview_tokens = sorted(
        enriched_tokens,
        key=lambda t: t.get("risk_reward", 0),
        reverse=True,
    )[:5]
    logger.info("\u2139\ufe0f Top 5 tokens before filtering:")
    for t in preview_tokens:
        base_amount = 10
        tp = round(t.get("price", 0) * 1.10, 6)
        sl = round(t.get("price", 0) * 0.95, 6)
        expected = calculate_expected_profit(
            t.get("price", 0), tp, base_amount, sl
        )
        score = score_token(t)
        logger.info(
            "• %s rr=%.2f rsi=%.2f mom=%.2f score=%.2f exp=%.2f tp=%s sl=%s",
            t.get("symbol"),
            t.get("risk_reward", 0),
            t.get("indicators", {}).get("rsi", 0),
            t.get("momentum", 0),
            score,
            expected,
            tp,
            sl,
        )

    # Пошук кандидатів на купівлю
    buy_candidates = filter_adaptive_smart_buy(enriched_tokens)
    strategy = "rsi_dip"
    # Прибираємо з buy ті токени, що вже в sell
    buy_candidates = [c for c in buy_candidates if c["symbol"] not in sell_symbols]

    if not buy_candidates:
        logger.warning("⚠️ Немає ідеальних кандидатів, шукаємо альтернативи...")
        buy_candidates = filter_fallback_best_candidates(enriched_tokens)
        buy_candidates = [c for c in buy_candidates if c["symbol"] not in sell_symbols]
        strategy = "fallback"

    print(f"🔍 Кандидати на купівлю: {len(buy_candidates)}")

    top_buy_candidates = sorted(buy_candidates, key=score_token, reverse=True)[:5]

    buy_plan = []
    remaining = available_usdt

    updates: list[tuple[str, float, float]] = []
    recommended_buys = []

    for token in top_buy_candidates:
        if remaining < 1:
            break
        rr = token.get("risk_reward", 0)
        if rr > 5:
            amount = 20
        elif rr < 1.5:
            amount = 5
        else:
            amount = 10
        amount = min(amount, remaining)
        token["amount_usdt"] = amount

        price = token.get("price", 0)
        tp_price = round(price * 1.10, 6)
        sl_price = round(price * 0.95, 6)
        token["tp_price"] = tp_price
        token["sl_price"] = sl_price
        token["score"] = score_token(token)
        token["expected_profit"] = calculate_expected_profit(price, tp_price, amount, sl_price)

        symbol = token["symbol"]
        stop_price = price * 0.97
        recommended_buys.append(
            f"{symbol}: Купити на {amount} USDT, TP {tp_price}, SL {sl_price}, очік. прибуток {token['expected_profit']}"
        )

        if _maybe_update_orders(symbol, tp_price, sl_price):
            updates.append((f"{symbol.upper()}USDT", tp_price, sl_price))

        buy_plan.append(token)
        remaining -= amount

    report_lines = []
    report_lines.append(f"🕒 Звіт сформовано: {now.strftime('%Y-%m-%d %H:%M:%S')} (Kyiv)")
    report_lines.append("\n💰 Баланс:")
    for t in token_data:
        report_lines.append(f"{t['symbol']}: {t['amount']} ≈ ~{t['uah_value']}₴")

    total_uah = round(sum([t['uah_value'] for t in token_data]) + convert_to_uah(usdt_balance), 2)
    report_lines.append(f"\nЗагальний баланс: {total_uah}₴")
    report_lines.append("⸻")

    if sell_recommendations:
        report_lines.append("💸 Рекомендується продати:")
        for t in sell_recommendations:
            report_lines.append(f"{t['symbol']}: {t['amount']} ≈ ~{t['uah_value']}₴ (PnL = {t['pnl']}%)")
    else:
        report_lines.append("Наразі немає прибуткових активів для продажу")
    report_lines.append("⸻")

    if buy_plan:
        report_lines.append("📈 Рекомендується купити:")
        for rec in recommended_buys:
            report_lines.append(rec)
    else:
        report_lines.append("Наразі немає активів, що відповідають умовам Smart Buy Filter")
    report_lines.append("⸻")

    total_expected_profit = sum(t.get("expected_profit", 0) for t in buy_candidates)
    expected_profit_usdt = round(total_expected_profit, 2)
    expected_profit_uah = convert_to_uah(expected_profit_usdt)
    report_lines.append(f"💹 Очікуваний прибуток: {expected_profit_usdt} USDT ≈ ~{expected_profit_uah}₴ за 24г")
    report_lines.append("⸻")

    market_trend = get_sentiment()
    summary_data = {
        "balance": f"{total_uah}₴",
        "sell_candidates": [t["symbol"] for t in sell_recommendations],
        "buy_candidates": [t["symbol"] for t in buy_plan],
        "expected_profit": f"{expected_profit_uah}₴",
        "market_trend": market_trend,
        "strategy": strategy,
    }
    gpt_forecast = ask_gpt(summary_data)

    report = "\n".join(report_lines)

    keyboard = InlineKeyboardMarkup(row_width=2)

    for token in sell_recommendations:
        keyboard.insert(
            InlineKeyboardButton(
                text=f"\U0001F534 \u041F\u0440\u043E\u0434\u0430\u0442\u0438 {token['symbol']}",
                callback_data=f"sell:{token['symbol']}"
            )
        )

    for token in buy_plan:
        keyboard.insert(
            InlineKeyboardButton(
                text=f"\U0001F7E2 \u041A\u0443\u043F\u0438\u0442\u0438 {token['symbol']}",
                callback_data=f"buy:{token['symbol']}"
            )
        )
        keyboard.insert(
            InlineKeyboardButton(
                text=f"\U0001F6D2 \u041A\u0443\u043F\u0438\u0442\u0438 {token['symbol']}",
                callback_data=f"smartbuy_{token['symbol']}"
            )
        )

    for token in token_data:
        if token['pnl'] > 10:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"📉 Фіксувати прибуток ({token['symbol']})",
                    callback_data=f"takeprofit_{token['symbol']}"
                )
            ])

    return report, keyboard, updates, gpt_forecast



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
    MAX_LEN = 4000
    for i in range(0, len(gpt_text), MAX_LEN):
        await bot.send_message(chat_id, gpt_text[i:i + MAX_LEN])


def generate_daily_stats_report() -> str:
    return "⏳ Щоденний звіт тимчасово недоступний."


# Adaptive filters for selecting buy candidates
from utils import calculate_indicators, get_risk_reward_ratio, get_correlation_with_btc


def smart_buy_filter(candidates, min_rr=1.0, min_score=2.0, min_tp_sl_gap=0.02):
    """Return tokens that meet relaxed Smart Buy criteria.

    The new logic is intentionally simple and prints diagnostics for each
    rejected token so that it's clear why it didn't pass the filter.
    """

    filtered = []
    for token in candidates:
        try:
            rr = token.get("risk_reward", 0)
            score = token.get("score", 0)
            tp = token.get("tp_price")
            sl = token.get("sl_price")
            symbol = token.get("symbol")

            # ensure TP and SL look valid
            if not (tp and sl and tp > sl):
                print(f"[⛔] {symbol} пропущено: некоректні TP/SL")
                continue

            tp_sl_gap = (tp - sl) / sl if sl > 0 else 0

            if rr >= min_rr and score >= min_score and tp_sl_gap >= min_tp_sl_gap:
                filtered.append(token)
            else:
                print(
                    f"[❌] {symbol} відсіяно | RR: {rr}, SCORE: {score}, TP-SL GAP: {tp_sl_gap:.3f}"
                )
        except Exception as e:
            print(f"[⚠️] Помилка з токеном: {token.get('symbol', '???')} → {e}")
    return filtered


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

if __name__ == "__main__":
    import asyncio
    from telegram import Bot
    import os

    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHAT_ID = os.getenv("CHAT_ID")

    if TELEGRAM_TOKEN and CHAT_ID:
        bot = Bot(token=TELEGRAM_TOKEN)
        asyncio.run(daily_analysis_task(bot, int(CHAT_ID)))
    else:
        print("❌ TELEGRAM_TOKEN або CHAT_ID не встановлено")
