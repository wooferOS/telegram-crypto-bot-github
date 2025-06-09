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
    get_usdt_to_uah_rate,
    place_market_order,
    place_limit_sell_order,
    get_open_orders,
    update_tp_sl_order,
)
from gpt_utils import ask_gpt
from utils import convert_to_uah, calculate_rr, calculate_indicators, get_sector, analyze_btc_correlation
from coingecko_api import get_sentiment
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


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


def generate_zarobyty_report() -> tuple[str, InlineKeyboardMarkup, list]:
    """Return daily profit report text and keyboard."""
    balances = get_binance_balances()
    usdt_balance = balances.get("USDT", 0)
    if usdt_balance is None:
        usdt_balance = 0

    token_data = []
    now = datetime.datetime.now(pytz.timezone("Europe/Kyiv"))

    for symbol, amount in balances.items():
        if symbol == "USDT" or amount == 0:
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

    sell_recommendations = [t for t in token_data if t['pnl'] > 1.0]

    exchange_rate_uah = get_usdt_to_uah_rate()
    usdt_from_sales = sum([t["uah_value"] for t in sell_recommendations]) / exchange_rate_uah
    available_usdt = round(usdt_balance + usdt_from_sales, 2)

    symbols_from_balance = set(t['symbol'].upper() for t in token_data)
    market_symbols = set(s.upper() for s in get_top_tokens(limit=50))
    symbols_to_analyze = symbols_from_balance.union(market_symbols)

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
        ema_trend = indicators.get("EMA_5", 0) > indicators.get("EMA_8", 0) > indicators.get("EMA_13", 0)

        enriched_tokens.append(
            {
                "symbol": symbol,
                "price": price,
                "risk_reward": rr,
                "sector": sector,
                "btc_corr": btc_corr,
                "volume_change_24h": volume_change,
                "indicators": {
                    "rsi": indicators["RSI"],
                    "macd_signal": indicators["MACD"],
                    "ema_trend": ema_trend,
                },
            }
        )

    # Пошук кандидатів на купівлю
    buy_candidates = filter_adaptive_smart_buy(enriched_tokens)

    if not buy_candidates:
        logger.warning("⚠️ Немає ідеальних кандидатів, шукаємо альтернативи...")
        buy_candidates = filter_fallback_best_candidates(enriched_tokens)

    top_buy_candidates = sorted(buy_candidates, key=lambda x: x["risk_reward"], reverse=True)[:5]

    max_per_token = 10
    buy_plan = []
    remaining = available_usdt

    for token in top_buy_candidates:
        if remaining < 1:
            break
        amount = min(max_per_token, remaining)
        token["amount_usdt"] = amount
        buy_plan.append(token)
        remaining -= amount

    recommended_buys = []
    updates: list[tuple[str, float, float]] = []
    for token in buy_plan:
        price = token["price"]
        symbol = token["symbol"]
        stop_price = price * 0.97  # 3% нижче — умовний стоп
        recommended_buys.append(
            f"{symbol}: Купити на {token['amount_usdt']} USDT, стоп ≈ {round(stop_price, 4)}"
        )

        tp_price = round(price * 1.10, 6)
        sl_price = round(price * 0.95, 6)
        if _maybe_update_orders(symbol, tp_price, sl_price):
            updates.append((f"{symbol.upper()}USDT", tp_price, sl_price))

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

    expected_profit_usdt = round(sum([t["amount_usdt"] * t["risk_reward"] for t in buy_plan]), 2)
    expected_profit_uah = convert_to_uah(expected_profit_usdt)
    report_lines.append(f"💹 Очікуваний прибуток: {expected_profit_usdt} USDT ≈ ~{expected_profit_uah}₴ за 24г")
    report_lines.append("⸻")

    market_trend = get_sentiment()
    summary_data = {
        "balance": f"{total_uah}₴",
        "recommended_sell": ", ".join([t["symbol"] for t in sell_recommendations]) or "Немає",
        "recommended_buy": "; ".join(recommended_buys) or "Немає",
        "profit": f"{expected_profit_uah}₴",
        "market_trend": market_trend,
    }
    gpt_forecast = ask_gpt(summary_data)
    report_lines.append(f"🧠 Прогноз GPT:\n{gpt_forecast}")

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

    return report, keyboard, updates



def generate_daily_stats_report() -> str:
    """Temporary stub for daily stats command."""
    return "\u23F3 \u041F\u043E\u043A\u0438 \u0449\u043E \u0449\u043E\u0434\u0435\u043D\u043D\u0438\u0439 \u0437\u0432\u0456\u0442 \u043D\u0435 \u0440\u0435\u0430\u043B\u0456\u0437\u043E\u0432\u0430\u043D\u043E."


async def daily_analysis_task(bot, chat_id: int) -> None:
    """Run daily analysis and notify about TP/SL updates."""
    report, _, updates = generate_zarobyty_report()
    await bot.send_message(chat_id, report)
    for symbol, tp_price, sl_price in updates:
        await bot.send_message(
            chat_id,
            f"\u267B\ufe0f Ордер оновлено: {symbol} — новий TP: {tp_price}, SL: {sl_price}"
        )


async def send_zarobyty_forecast(bot, chat_id: int) -> None:
    """Placeholder for forecast sending."""
    await bot.send_message(chat_id, "\u23F3 \u0424\u0443\u043D\u043A\u0446\u0456\u044F \u043F\u0440\u043E\u0433\u043D\u043E\u0437\u0443 \u043D\u0435 \u0440\u0435\u0430\u043B\u0456\u0437\u043E\u0432\u0430\u043D\u0430.")


def generate_daily_stats_report() -> str:
    return "⏳ Щоденний звіт тимчасово недоступний."


# Adaptive filters for selecting buy candidates
from utils import calculate_indicators, get_risk_reward_ratio, get_correlation_with_btc


def filter_adaptive_smart_buy(candidates):
    filtered = []
    for token in candidates:
        rsi = token.get("indicators", {}).get("rsi", 50)
        macd_signal = token.get("indicators", {}).get("macd_signal", "neutral")
        rr = token.get("risk_reward", 0)
        corr = token.get("btc_corr", 1)
        vol_change = token.get("volume_change_24h", 0)
        ema_trend = token.get("indicators", {}).get("ema_trend", False)

        strong_signals = sum(
            [
                rsi < 40,
                macd_signal == "bullish",
                rr >= 1.5,
                corr < 0.7,
                vol_change > 0,
                ema_trend,
            ]
        )

        if strong_signals >= 2:
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
