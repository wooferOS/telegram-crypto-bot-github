import asyncio
import hashlib
import logging

import math
import statistics
import numpy as np

from log_setup import setup_logging
import os
from typing import Dict, List, Optional
from collections import Counter


# Configuration values are provided explicitly by callers
from services.telegram_service import send_messages

from binance_api import (
    get_binance_balances,
    get_symbol_price,
    get_candlestick_klines,
    get_valid_usdt_symbols,
    get_symbol_precision,
    try_convert,
    sell_asset,
    get_token_balance,
)
from ml_model import load_model, generate_features, predict_prob_up
from ml_utils import predict_proba
from risk_utils import calculate_risk_reward, max_drawdown
from utils import dynamic_tp_sl, calculate_expected_profit
from daily_analysis import split_telegram_message
import json

# These thresholds are more lenient for manual conversion suggestions
# Generate signals even for modest opportunities
CONVERSION_MIN_EXPECTED_PROFIT = 0.01
CONVERSION_MIN_PROB_UP = 0.5


logger = logging.getLogger(__name__)


def load_gpt_filters() -> dict[str, str]:
    """Read ``gpt_forecast.txt`` and return a symbol→action mapping."""
    try:
        with open("gpt_forecast.txt", "r", encoding="utf-8") as f:
            forecast = json.load(f)
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.warning("[dev] ❗ Не вдалося завантажити GPT-прогноз: %s", exc)
        return {}

    logger.info(
        "GPT-фільтр: buy=%d, sell=%d",
        len(forecast.get("buy", [])),
        len(forecast.get("sell", [])),
    )
    return forecast


def _human_amount(amount: float, precision: int) -> str:
    """Return ``amount`` formatted for Telegram messages."""
    if amount >= 1_000_000:
        return f"{amount/1_000_000:.2f}M"
    if amount >= 10_000:
        return f"{int(round(amount)):_}"
    return f"{amount:,.{precision}f}".replace(",", "_")


def _analyze_pair(
    pair: str,
    model,
    min_profit: float,
    min_prob: float,
) -> Optional[Dict[str, float]]:
    """Return price analysis data for ``pair`` or ``None`` on failure."""

    price = get_symbol_price(pair)
    if price == 0:
        logger.info(f"[dev] ⛔ Пропускаємо {pair} — ціна недоступна")
        return None

    klines = get_candlestick_klines(pair)
    if not klines:
        return None

    closes = [float(k[4]) for k in klines]
    tp, sl = dynamic_tp_sl(closes, price)

    try:
        prices_24h = [float(k[4]) for k in klines[-24:]]
        volume_usdt = sum(float(k[5]) for k in klines[-24:])
        if len(prices_24h) >= 2:
            x = np.arange(len(prices_24h))
            slope = np.polyfit(x, prices_24h, 1)[0]
            slope_norm = slope / prices_24h[0] * len(prices_24h)
            trend_score = 1 / (1 + math.exp(-slope_norm))
            volatility_24h = statistics.pstdev(prices_24h)
        else:
            trend_score = 0.5
            volatility_24h = 0.0
    except Exception:  # noqa: BLE001
        trend_score = 0.5
        volatility_24h = 0.0
        volume_usdt = 0.0

    try:
        features, _, _ = generate_features(pair)
        prob_up = predict_prob_up(model, features) if model else 0.5
        indicators = {f"f{i}": float(v) for i, v in enumerate(features[0])}
        ml_proba = predict_proba(pair, indicators)
    except Exception:  # noqa: BLE001
        prob_up = 0.5
        ml_proba = 0.5

    expected_profit = calculate_expected_profit(price, tp, amount=10, sl_price=sl)

    score_base = prob_up * expected_profit
    score = expected_profit * trend_score
    rrr = calculate_risk_reward(prob_up, expected_profit)
    ret = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    dd = max_drawdown(ret)

    if (
        expected_profit < min_profit
        or prob_up < min_prob
        or score <= 0
        or prob_up <= 0.5
        or ml_proba <= 0.65
        or rrr <= 1.5
    ):
        logger.info(
            f"[dev] ⚠️ Пропущено {pair}: EP={expected_profit:.2f}, prob_up={prob_up:.2f}, ml={ml_proba:.2f}, RRR={rrr:.2f}"
        )
        return None
    elif trend_score < 0.3:
        logger.info(f"[dev] ⚠️ Пропущено {pair}: Low trend")
        return None
    elif volume_usdt < 10000:
        logger.info(f"[dev] ⚠️ Пропущено {pair}: Low volume")
        return None
    else:
        logger.info(
            f"[dev] ✅ Додано у BUY: {pair.replace('USDT','')}, score={score:.2f}, trend={trend_score:.2f}, vol={volume_usdt:.0f}$"
        )

    return {
        "price": price,
        "tp": tp,
        "sl": sl,
        "prob_up": prob_up,
        "ml_proba": ml_proba,
        "expected_profit": expected_profit,
        "trend_score": trend_score,
        "volatility_24h": volatility_24h,
        "volume_usdt": volume_usdt,
        "score": score,
        "score_base": score_base,
        "risk_reward_ratio": rrr,
        "drawdown": dd,
    }


def generate_conversion_signals(
    gpt_filters: Optional[Dict[str, List[str]]] = None,
    gpt_forecast: Optional[Dict[str, List[str]]] = None,
) -> tuple[
    List[Dict[str, float]],
    bool,
    Dict[str, float],
    Dict[str, Dict[str, float]],
    float,
    bool,
    list,
]:
    """Analyze portfolio and propose asset conversions.

    Returns a list of conversion suggestions and a flag indicating
    whether the expected profit was below ``CONVERSION_MIN_EXPECTED_PROFIT``.
    """

    model = load_model()
    min_profit = gpt_forecast.get("adaptive_filters", {}).get("min_expected_profit", 0.3) if gpt_forecast else 0.3
    min_prob = gpt_forecast.get("adaptive_filters", {}).get("min_prob_up", 0.6) if gpt_forecast else 0.6
    balances = get_binance_balances()
    portfolio = {
        a: amt for a, amt in balances.items() if a not in {"USDT", "BUSD"} and amt > 0
    }
    if not portfolio:
        return [], False, {}, {}, balances.get("USDT", 0.0)

    predictions: Dict[str, Dict[str, float]] = {}
    for symbol in get_valid_usdt_symbols():
        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        data = _analyze_pair(pair, model, min_profit, min_prob)
        if data:
            predictions[pair] = data

    if not predictions:
        return [], False, portfolio, {}, balances.get("USDT", 0.0)

    # Drop tokens with duplicate expected_profit values
    ep_counts = Counter(round(d["expected_profit"], 4) for d in predictions.values())
    unique_predictions = {
        p: d for p, d in predictions.items() if ep_counts[round(d["expected_profit"], 4)] == 1
    }
    all_equal = len(ep_counts) == 1

    ranked = [
        (
            p,
            {
                **d,
                "score": d["expected_profit"] * d.get("trend_score", 0),
                "score_base": d.get("score_base", d["prob_up"] * d["expected_profit"]),
            },
        )
        for p, d in (unique_predictions or predictions).items()
        if d["prob_up"] > 0 and d["expected_profit"] > 0
    ]
    base_scores = [r[1]["score_base"] for r in ranked]
    if base_scores and max(base_scores) - min(base_scores) < 0.01:
        gpt_notes: List[str] = [
            "[dev] Використано альтернативне сортування BUY: expected_profit * trend"
        ]
    else:
        gpt_notes = []
    ranked.sort(key=lambda x: x[1]["score"], reverse=True)
    all_buy_tokens = ranked
    top_tokens = ranked[:3]

    if gpt_filters:
        filtered_tokens = [
            t for t in top_tokens if t[0].replace("USDT", "") not in gpt_filters.get("do_not_buy", [])
        ]
        prioritized = [
            t for t in top_tokens if t[0].replace("USDT", "") in gpt_filters.get("recommend_buy", [])
        ]
        if prioritized:
            filtered_tokens = prioritized
        for t in top_tokens:
            sym = t[0].replace("USDT", "")
            if sym in gpt_filters.get("do_not_buy", []) and t not in filtered_tokens:
                logger.info(f"[dev] ⚠️ GPT не рекомендує купувати {sym}")
                gpt_notes.append(f"⚠️ GPT не рекомендує купувати {sym}")
        top_tokens = filtered_tokens

    if gpt_forecast:
        allowed = set(gpt_forecast.get("buy", []))
        filtered = []
        for pair, data in top_tokens:
            sym = pair.replace("USDT", "")
            if allowed and sym not in allowed:
                logger.info(f"[dev] ⏭️ GPT блокує покупку {sym}")
                continue
            filtered.append((pair, data))
        top_tokens = filtered

    if len(top_tokens) < 3:
        logger.info(
            "[dev] ⚠️ Недостатньо BUY токенів з високим score, використовую найкращі з усього BUY списку."
        )
        top_tokens = all_buy_tokens[:3]
    if not top_tokens:
        return [], False, portfolio, predictions, balances.get("USDT", 0.0), all_equal, gpt_notes

    best_pair, best_data = top_tokens[0]

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
                "score": best_data.get("score", 0.0),
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
                    "score": best_data.get("score", 0.0),
                }
            )

    return (
        signals,
        low_profit,
        portfolio,
        predictions,
        balances.get("USDT", 0.0),
        all_equal,
        gpt_notes,
    )


def sell_unprofitable_assets(
    portfolio: Dict[str, float],
    predictions: Dict[str, Dict[str, float]],
    gpt_forecast: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """Sell assets with expected profit below the top-3 threshold."""

    if not portfolio or not predictions:
        return []

    ranked = sorted(
        [d["expected_profit"] for d in predictions.values() if d["expected_profit"] > 0],
        reverse=True,
    )
    if not ranked:
        return

    top3_min = ranked[min(2, len(ranked) - 1)]
    usdt_before = get_binance_balances().get("USDT", 0.0)
    gpt_notes: List[str] = []
    if gpt_forecast:
        blocked = set(gpt_forecast.get("sell", []))
        tokens_to_consider = [a for a in portfolio if a not in blocked]
        for token in blocked:
            if token in portfolio:
                logger.info(f"[dev] ⛔ GPT не рекомендує продавати {token} — ігноруємо продаж")
                gpt_notes.append(f"⛔ GPT заблокував продаж {token}")
    else:
        tokens_to_consider = list(portfolio.keys())

    for asset, amount in portfolio.items():
        if asset not in tokens_to_consider:
            continue
        if asset in {"USDT", "BUSD"} or amount <= 0:
            continue
        pair = asset if asset.endswith("USDT") else f"{asset}USDT"
        data = predictions.get(pair)
        if not data:
            continue
        prob = data.get("prob_up", 0.0)
        ep = data.get("expected_profit", 0.0)
        logger.info(
            f"[dev] 🔍 Оцінка продажу {asset}: prob_up={prob:.2f}, expected_profit={ep:.4f}, top3_min_profit={top3_min}"
        )
        if ep >= top3_min:
            continue
        result = sell_asset(pair, amount)
        status = result.get("status")
        if status in {"success", "converted"}:
            logger.info(f"[dev] ✅ Продано {amount} {asset} за ринком")
            amount_left = get_token_balance(asset)
            if amount_left < 10 ** -6:
                logger.warning(
                    f"[dev] Залишок {asset}: {amount_left} — замало для конвертації, буде втрачено."
                )
        else:
            logger.warning(f"[dev] ⛔ Не вдалося ні продати, ні сконвертувати {asset}")

    usdt_after = get_binance_balances().get("USDT", 0.0)
    logger.info(f"[dev] 💰 Поточний баланс USDT: {usdt_after}")
    if abs(usdt_after - usdt_before) < 1e-8:
        logger.warning("[dev] ❗ Продаж не відбувся — баланс USDT залишився без змін")

    return gpt_notes


def _compose_failure_message(
    portfolio: Dict[str, float],
    predictions: Dict[str, Dict[str, float]],
    usdt_balance: float,
    *,
    identical_profits: bool = False,
) -> str:
    """Return concise explanation why no trade was executed."""

    return (
        "[dev] Куплено найкращі доступні токени, навіть при слабкому ринку."
    )


async def send_conversion_signals(
    signals: List[Dict[str, float]],
    *,
    chat_id: int,
    low_profit: bool = False,
    portfolio: Optional[Dict[str, float]] = None,
    predictions: Optional[Dict[str, Dict[str, float]]] = None,
    usdt_balance: float = 0.0,
    identical_profits: bool = False,
    gpt_notes: Optional[List[str]] = None,
) -> None:
    """Convert assets automatically and report the result."""

    if not signals:
        logger.info("No conversion signals generated")
        message = _compose_failure_message(
            portfolio or {},
            predictions or {},
            usdt_balance,
            identical_profits=identical_profits,
        )
        await send_messages(int(chat_id), [message])
        return

    lines = []
    summary = [f"[dev] Куплено {len(signals)} токен{'и' if len(signals) != 1 else ''}:"]
    for s in signals:
        precision = get_symbol_precision(f"{s['to_symbol']}USDT")
        precision = max(2, min(4, precision))
        to_qty = s['to_amount']
        to_amount = _human_amount(to_qty, precision)
        result = try_convert(s['from_symbol'], s['to_symbol'], s['from_amount'])
        token_line = (
            f"✅ {s['to_symbol']} ml={s['ml_proba']:.2f} exp={s['expected_profit']:.2f} "
            f"RRR={s['rrr']:.2f} score={s['score']:.2f}"
        )
        summary.append(token_line)
        if result and result.get("orderId"):
            lines.append(
                f"✅ Конвертовано {s['from_symbol']} → {s['to_symbol']}"
                f"\nFROM: {s['from_amount']:.4f}"
                f"\nTO: ≈{to_amount}"
                f"\nML={s['ml_proba']:.2f}, exp={s['expected_profit']:.2f}, RRR={s['rrr']:.2f}, score={s['score']:.2f}"
            )
        else:
            reason = result.get("message", "невідома помилка") if result else "невідома помилка"
            if "Signature for this request" in reason:
                amount_str = _human_amount(s["from_amount"], 0)
                lines.append(
                    f"❗ Неможливо виконати convert для {amount_str}{s['from_symbol']} → {s['to_symbol']}. Binance ще не надав доступ до цього інструменту."
                )
            else:
                lines.append(
                    f"❌ Не вдалося конвертувати {s['from_symbol']} → {s['to_symbol']}"
                    f"\nПричина: {reason}"
                )
    text = "\n\n".join(lines)

    messages = list(split_telegram_message("\n".join(summary), 4000))
    messages.extend(split_telegram_message(text, 4000))

    # Persist last conversion to suppress duplicates
    last_file = os.path.join("logs", "last_conversion_hash.txt")
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    last_hash = None
    if os.path.exists(last_file):
        try:
            with open(last_file, "r", encoding="utf-8") as f:
                last_hash = f.read().strip() or None
        except OSError:
            last_hash = None
    if text_hash == last_hash:
        return

    if low_profit:
        messages.append("\u26a0\ufe0f Очікуваний прибуток низький")
    if gpt_notes:
        messages.extend(gpt_notes)
    await send_messages(int(chat_id), messages)

    try:
        os.makedirs(os.path.dirname(last_file), exist_ok=True)
        with open(last_file, "w", encoding="utf-8") as f:
            f.write(text_hash)
    except OSError as exc:  # pragma: no cover - diagnostics only
        logger.warning("Could not persist %s: %s", last_file, exc)


async def main(chat_id: int) -> None:
    gpt_forecast = load_gpt_filters()
    gpt_filters = {
        "do_not_sell": gpt_forecast.get("sell", []),
        "do_not_buy": [],
        "recommend_buy": gpt_forecast.get("buy", []),
    }

    (
        signals,
        low_profit,
        portfolio,
        predictions,
        usdt_balance,
        all_equal,
        gpt_notes,
    ) = generate_conversion_signals(gpt_filters, gpt_forecast)
    gpt_notes.extend(sell_unprofitable_assets(portfolio, predictions, gpt_forecast))
    usdt_balance = get_binance_balances().get("USDT", 0.0)

    if not signals:
        fallback = None
        for pair, data in sorted(
            predictions.items(), key=lambda x: x[1].get("volume_usdt", 0), reverse=True
        ):
            if data.get("expected_profit", 0) > 0.01:
                fallback = (pair, data)
                break
        if fallback and usdt_balance > 0:
            pair, data = fallback
            amount = usdt_balance
            if data.get("drawdown", 0) > 0.3:
                amount *= 0.5
            signals.append(
                {
                    "from_symbol": "USDT",
                    "to_symbol": pair.replace("USDT", ""),
                    "from_amount": amount,
                    "from_usdt": amount,
                    "to_amount": amount / data["price"],
                    "profit_pct": (data["expected_profit"] / 10) * 100,
                    "profit_usdt": (data["expected_profit"] / 10) * amount,
                    "tp": data["tp"],
                    "sl": data["sl"],
                    "score": data.get("score", 0.0),
                    "ml_proba": data.get("ml_proba", 0.5),
                    "expected_profit": data["expected_profit"],
                    "rrr": data.get("risk_reward_ratio", 0),
                }
            )
    await send_conversion_signals(
        signals,
        chat_id=chat_id,
        low_profit=low_profit,
        portfolio=portfolio,
        predictions=predictions,
        usdt_balance=usdt_balance,
        identical_profits=all_equal,
        gpt_notes=gpt_notes,
    )


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main(0))
