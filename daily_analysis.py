# ✅ Еталонна логіка GPT-звіту /zarobyty (v2.0) — повна реалізація
# Мета: максимізувати прибуток за добу, діючи в рамках поточного балансу Binance

import datetime
import pytz
import statistics

from binance_api import (
    get_binance_balances,
    get_symbol_price,
    get_price_history_24h as get_price_history,
    get_price_history_24h as get_klines,
    get_my_trades,
    get_top_tokens,
)
from gpt import ask_gpt
from utils import convert_to_uah, calculate_rr, calculate_indicators, get_sector, analyze_btc_correlation
from keyboards import zarobyty_keyboard


def generate_zarobyty_report():
    balances = get_binance_balances()
    usdt_balance = balances.get("USDT", 0)

    token_data = []
    now = datetime.datetime.now(pytz.timezone("Europe/Kyiv"))

    for symbol, amount in balances.items():
        if symbol == "USDT" or amount == 0:
            continue

        price = get_symbol_price(symbol)
        uah_value = convert_to_uah(price * amount)
        price_history = get_price_history(symbol)
        klines = get_klines(symbol)
        trades = get_my_trades(symbol)

        indicators = calculate_indicators(klines)
        average_buy_price = sum([t['price'] * t['qty'] for t in trades]) / sum([t['qty'] for t in trades]) if trades else price
        pnl_percent = ((price - average_buy_price) / average_buy_price) * 100
        rr = calculate_rr(klines)
        volume_24h = price_history.get("quoteVolume", 0)
        sector = get_sector(symbol)
        btc_corr = analyze_btc_correlation(symbol)

        token_data.append({
            "symbol": symbol,
            "amount": amount,
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

    symbols_from_balance = set(t['symbol'].upper() for t in token_data)
    market_symbols = set(s.upper() for s in get_top_tokens(limit=50))
    symbols_to_analyze = symbols_from_balance.union(market_symbols)

    buy_candidates = []
    for symbol in symbols_to_analyze:
        price = get_symbol_price(symbol)
        klines = get_klines(symbol)
        indicators = calculate_indicators(klines)
        rr = calculate_rr(klines)
        sector = get_sector(symbol)
        price_stats = get_price_history(symbol)
        volume = price_stats.get("quoteVolume", 0)
        volumes = [float(k[5]) for k in klines]
        avg_volume = statistics.fmean(volumes[-20:]) if volumes else 0
        btc_corr = analyze_btc_correlation(symbol)

        support = indicators.get("support")
        resistance = indicators.get("resistance")
        is_near_resistance = price >= resistance * 0.98 if resistance else False

        ema_uptrend = (
            indicators.get("EMA_5", 0) > indicators.get("EMA_8", 0) > indicators.get("EMA_13", 0)
        )

        # ✅ Smart Buy Filter:
        # - RSI < 30 (перепроданість)
        # - MACD == 'bullish' (сигнал на розворот)
        # - RR > 2.0 (співвідношення прибуток/ризик)
        # - Volume > average (підтвердження сили тренду)
        # - EMA 5 > EMA 8 > EMA 13 (ап-тренд)
        # - Не біля resistance (опір)
        # - BTC correlation < 0.5 (незалежність)
        if (
            indicators["RSI"] < 30
            and indicators["MACD"] == "bullish"
            and rr > 2
            and volume > avg_volume
            and btc_corr < 0.5
            and not is_near_resistance
            and ema_uptrend
        ):
            stop_price = round(price * 0.97, 4)
            buy_candidates.append({
                "symbol": symbol,
                "price": price,
                "stop": stop_price,
                "rr": rr,
                "volume": volume,
                "sector": sector,
                "rsi": indicators["RSI"],
                "macd": indicators["MACD"],
                "btc_corr": btc_corr,
                "support": support,
                "resistance": resistance
            })

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

    if buy_candidates:
        report_lines.append("📈 Рекомендується купити:")
        for b in buy_candidates:
            indicators = calculate_indicators(get_klines(b['symbol']))
            report_lines.append(
                f"{b['symbol']}: інвестувати {round(usdt_balance / len(buy_candidates), 2)} USDT (стоп: {b['stop']})\nRR = {b['rr']:.2f}, RSI = {b['rsi']:.1f}, MACD = {b['macd']}, Обсяг = {int(b['volume'])}, Сектор = {b['sector']}, BTC Corr = {b['btc_corr']:.2f}, Підтримка = {int(b['support'])}, Опір = {int(b['resistance'])}\nEMA 5/8/13 = {indicators['EMA_5']:.4f} / {indicators['EMA_8']:.4f} / {indicators['EMA_13']:.4f}"
            )
    else:
        report_lines.append("Наразі немає активів, що відповідають умовам Smart Buy Filter")
    report_lines.append("⸻")

    expected_profit_usdt = round((sum([b['rr'] for b in buy_candidates]) / len(buy_candidates)) * (usdt_balance / 100) if buy_candidates else 0, 2)
    expected_profit_uah = convert_to_uah(expected_profit_usdt)
    report_lines.append(f"💹 Очікуваний прибуток: {expected_profit_usdt} USDT ≈ ~{expected_profit_uah}₴ за 24г")
    report_lines.append("⸻")

    summary = ask_gpt("Сформуй короткий інвест-звіт на 24г для крипто-портфеля", context="\n".join(report_lines))
    report_lines.append(f"🧠 Прогноз GPT:\n{summary}")

    return "\n".join(report_lines), zarobyty_keyboard(buy_candidates, sell_recommendations)
