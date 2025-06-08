# ✅ Еталонна логіка GPT-звіту /zarobyty (v2.0) — повна реалізація
# Мета: максимізувати прибуток за добу, діючи в рамках поточного балансу Binance

import datetime
import pytz

from binance_api import (
    get_binance_balances,
    get_token_price,
    get_price_history,
    get_klines,
    get_my_trades,
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

        price = get_token_price(symbol)
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

    buy_candidates = []
    for symbol in ["GFT", "PEPE", "DOGE", "1000SATS", "NOT", "ADA", "TRX", "AMB"]:
        price = get_token_price(symbol)
        klines = get_klines(symbol)
        indicators = calculate_indicators(klines)
        rr = calculate_rr(klines)
        sector = get_sector(symbol)
        volume = get_price_history(symbol).get("quoteVolume", 0)
        btc_corr = analyze_btc_correlation(symbol)

        if indicators["RSI"] < 30 and indicators["MACD"] == "bullish" and rr > 2 and volume > 0 and btc_corr < 0.5:
            stop_price = round(price * 0.97, 4)
            buy_candidates.append({
                "symbol": symbol,
                "price": price,
                "stop": stop_price,
                "rr": rr,
                "volume": volume,
                "sector": sector,
                "rsi": indicators["RSI"],
                "macd": indicators["MACD"]
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
            report_lines.append(f"{b['symbol']}: інвестувати {round(usdt_balance / len(buy_candidates), 2)} USDT (стоп: {b['stop']})\nRR = {b['rr']:.2f}, RSI = {b['rsi']:.1f}, MACD = {b['macd']}, Обсяг = {int(b['volume'])}, Сектор = {b['sector']}, BTC Corr = {b['btc_corr']:.2f}")
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
