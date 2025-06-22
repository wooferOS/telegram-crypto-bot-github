import asyncio
import hashlib
import logging

import math
import statistics
import numpy as np
import datetime

from log_setup import setup_logging
import os
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
from config import (
    MIN_EXPECTED_PROFIT,
    MIN_PROB_UP,
)
from typing import Dict, List, Optional
from collections import Counter
from constants import TRADE_SUMMARY


# Configuration values are provided explicitly by callers
from services.telegram_service import send_messages

from binance_api import (
    get_binance_balances,
    get_symbol_price,
    get_candlestick_klines,
    get_valid_usdt_symbols,
    get_symbol_precision,
    try_convert,
    convert_to_usdt,
    sell_asset,
    get_token_balance,
    place_take_profit_order,
    place_stop_loss_order,
    refresh_valid_pairs,
    VALID_PAIRS,
)
from ml_model import (
    load_model,
    generate_features,
    predict_prob_up,
    predict_trade_success,
)
from ml_utils import predict_proba
from risk_utils import calculate_risk_reward, max_drawdown
from utils import dynamic_tp_sl, calculate_expected_profit
from binance_api import (
    get_min_notional,
    get_lot_step,
    market_buy_symbol_by_amount,
    get_whale_alert,
    market_buy,
    market_sell,
)
from daily_analysis import split_telegram_message
from history import add_trade
import json
from binance.helpers import round_step_size

# These thresholds are more lenient for manual conversion suggestions
# Generate signals even for modest opportunities
CONVERSION_MIN_EXPECTED_PROFIT = 0.01
CONVERSION_MIN_PROB_UP = 0.5
FALLBACK_MIN_SCORE = 0.25


logger = logging.getLogger(__name__)


def load_gpt_filters() -> dict[str, List[str]]:
    """Read ``gpt_forecast.txt`` and return forecast data."""

    try:
        with open("gpt_forecast.txt", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.warning("[dev] ❗ Не вдалося завантажити GPT-прогноз: %s", exc)
        return {"recommend_buy": [], "do_not_buy": []}

    if not isinstance(data, dict):
        return {"recommend_buy": [], "do_not_buy": []}

    logger.info(
        "GPT-фільтр: buy=%d, sell=%d",
        len(data.get("recommend_buy", [])),
        len(data.get("do_not_buy", [])),
    )

    return {
        "recommend_buy": data.get("recommend_buy", []),
        "do_not_buy": data.get("do_not_buy", []),
    }


def load_predictions() -> Dict[str, Dict[str, float]]:
    """Return stored predictions from disk if available."""
    path = os.path.join("logs", "predictions.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.warning("[dev] ❗ Не вдалося завантажити predictions: %s", exc)
    return {}


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
        logger.info(f"[dev] Пропускаємо {pair} — ціна недоступна")
        return None

    klines = get_candlestick_klines(pair)
    if not klines:
        return None

    closes = [float(k[4]) for k in klines]
    tp, sl = dynamic_tp_sl(closes, price)

    whale_alert = get_whale_alert(pair)

    try:
        last4 = [float(k[4]) for k in klines[-4:]]
        vol = statistics.pstdev(last4) if len(last4) >= 2 else 0.0
        volatility_weight = 1 + (vol / price if price else 0)
    except Exception:  # noqa: BLE001
        volatility_weight = 1.0

    try:
        last12 = [float(k[4]) for k in klines[-12:]]
        trend_weight = 1.1 if len(last12) >= 2 and last12[-1] > last12[0] else 0.9
    except Exception:  # noqa: BLE001
        trend_weight = 1.0

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
    final_score = prob_up * expected_profit * trend_weight * volatility_weight
    rrr = calculate_risk_reward(prob_up, expected_profit)
    ret = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    dd = max_drawdown(ret)

    token_data_ml = {
        "expected_profit": expected_profit,
        "prob_up": prob_up,
        "score": final_score,
        "whale_alert": whale_alert,
        "volume": volume_usdt,
        "rsi": float(features[0][3]) if 'features' in locals() else 0.0,
        "trend": trend_score,
        "previous_gain": ret[-1] if ret else 0.0,
    }
    ml_prob_history = predict_trade_success(token_data_ml)
    final_score = ml_prob_history * expected_profit

    if expected_profit < 0.01 or prob_up < 0.45 or rrr < 1.0 or ml_proba < 0.45:
        logger.info(
            f"[dev] Пропущено {pair}: EP={expected_profit:.2f}, prob_up={prob_up:.2f}, ml={ml_proba:.2f}, RRR={rrr:.2f}"
        )
        return None
    elif trend_score < 0.3:
        logger.info(
            f"[dev] Пропущено {pair}: Low trend EP={expected_profit:.2f}, prob_up={prob_up:.2f}, ml={ml_proba:.2f}, RRR={rrr:.2f}"
        )
        return None
    elif volume_usdt < 10000:
        logger.info(
            f"[dev] Пропущено {pair}: Low volume EP={expected_profit:.2f}, prob_up={prob_up:.2f}, ml={ml_proba:.2f}, RRR={rrr:.2f}"
        )
        return None
    else:
        logger.info(
            f"[dev] Додано у BUY: {pair.replace('USDT','')}, score={final_score:.2f}, trend={trend_score:.2f}, vol={volume_usdt:.0f}$"
        )

    return {
        "price": price,
        "tp": tp,
        "sl": sl,
        "prob_up": prob_up,
        "ml_proba": ml_proba,
        "ml_prob_history": ml_prob_history,
        "whale_alert": whale_alert,
        "expected_profit": expected_profit,
        "trend_score": trend_score,
        "volatility_24h": volatility_24h,
        "trend_weight": trend_weight,
        "volatility_weight": volatility_weight,
        "volume_usdt": volume_usdt,
        "score": final_score,
        "score_base": score_base,
        "risk_reward_ratio": rrr,
        "drawdown": dd,
    }


def filter_top_tokens(
    predictions: dict,
    limit: int = 3,
    gpt_forecast: Optional[Dict[str, List[str]]] = None,
) -> list[tuple[str, dict]]:
    """Filter and rank tokens by basic score with optional GPT filtering."""

    ranked: list[tuple[str, dict]] = []
    for pair, data in predictions.items():
        ep = data.get("expected_profit", 0.0)
        prob = data.get("prob_up", 0.0)
        score = prob * ep
        ranked.append((pair, {**data, "score": score}))

    ranked.sort(key=lambda x: x[1].get("score"), reverse=True)
    filtered = ranked[:limit]

    if gpt_forecast:
        filtered = [
            token
            for token in filtered
            if token[0].replace("USDT", "")
            not in gpt_forecast.get("do_not_buy", [])
        ]

    if not filtered:
        logger.warning("[dev] ⚠️ Усі токени відфільтровані GPT — fallback на top-3.")
        filtered = ranked[:limit]

    if not filtered:
        logger.warning(
            "[dev] ⚠️ Усі токени відфільтровані — fallback на top-3."
        )
        filtered = ranked[:3]

    logger.info("[dev] Після фільтрації: %s", filtered)

    return filtered
    

def generate_conversion_signals(
    gpt_filters: Optional[Dict[str, List[str]]] = None,
    gpt_forecast: Optional[Dict[str, List[str]]] = None,
) -> tuple[
    List[Dict[str, float]],
    List[str],
    List[str],
    List,
    List[str],
    str,
    Dict[str, List[str]] | None,
    Dict[str, Dict[str, float]],
]:
    """Analyze portfolio and propose asset conversions.

    Returns a list of conversion suggestions and a flag indicating
    whether the expected profit was below ``CONVERSION_MIN_EXPECTED_PROFIT``.
    """

    refresh_valid_pairs()
    logger.info("[dev] ✅ VALID_PAIRS оновлено: %d пар", len(VALID_PAIRS))
    if not VALID_PAIRS:
        logger.error(
            "[dev] ❌ VALID_PAIRS порожній — неможливо отримати дані з Binance"
        )
        return [], [], [], [], [], "", gpt_forecast

    model = load_model()
    min_profit = gpt_forecast.get("adaptive_filters", {}).get("min_expected_profit", 0.3) if gpt_forecast else 0.3
    min_prob = gpt_forecast.get("adaptive_filters", {}).get("min_prob_up", 0.6) if gpt_forecast else 0.6
    balances = get_binance_balances()
    portfolio = {a: amt for a, amt in balances.items() if a not in {"USDT", "BUSD"} and amt > 0}
    if not portfolio:
        return [], [], [], [], [], "", gpt_forecast

    predictions: Dict[str, Dict[str, float]] = {}
    market_pairs = [
        s if s.endswith("USDT") else f"{s}USDT" for s in get_valid_usdt_symbols()
    ]
    # ⚠️ Тимчасове обмеження для дебагу
    market_pairs = market_pairs[:50]

    for pair in market_pairs:
        logger.info(f"[dev] Аналізуємо {pair}...")
        data = _analyze_pair(pair, model, min_profit, min_prob)
        if data:
            predictions[pair] = data

    if not predictions:
        return [], [], [], [], [], "", gpt_forecast

    # Drop tokens with duplicate expected_profit values
    ep_counts = Counter(round(d.get('expected_profit'), 4) for d in predictions.values())
    unique_predictions = {p: d for p, d in predictions.items() if ep_counts[round(d.get('expected_profit'), 4)] == 1}
    all_equal = len(ep_counts) == 1

    ranked = [
        (
            p,
            {
                **d,
                "score_base": d.get("score_base", d.get('prob_up') * d.get('expected_profit')),
            },
        )
        for p, d in (unique_predictions or predictions).items()
        if d.get('expected_profit') >= 0 or d.get("score", 0) >= 0.01
    ]
    base_scores = [r[1].get("score_base") for r in ranked]
    if base_scores and max(base_scores) - min(base_scores) < 0.01:
        gpt_notes: List[str] = ["[dev] Використано альтернативне сортування BUY: expected_profit * trend"]
    else:
        gpt_notes = []
    ranked.sort(key=lambda x: x[1].get("score"), reverse=True)
    all_buy_tokens = ranked

    top_tokens = [r for r in ranked if r[1].get("expected_profit") > 0 and r[1].get("score") > 0]
    if not top_tokens:
        logger.warning("[dev] ⚠️ Жодна монета не пройшла фільтр очікуваного прибутку > 0")
        top_tokens = ranked[:3]  # fallback: хоча б щось купити
    else:
        top_tokens = top_tokens[:3]

    logger.info("[dev] top_tokens: %s", top_tokens)
    filtered_tokens = top_tokens

    if gpt_filters:
        filtered_tokens = [t for t in top_tokens if t[0].replace("USDT", "") not in gpt_filters.get("do_not_buy", [])]
        prioritized = [t for t in top_tokens if t[0].replace("USDT", "") in gpt_filters.get("recommend_buy", [])]
        if prioritized:
            filtered_tokens = prioritized
        for t in top_tokens:
            sym = t[0].replace("USDT", "")
            if sym in gpt_filters.get("do_not_buy", []) and t not in filtered_tokens:
                logger.info(f"[dev] GPT не рекомендує купувати {sym}")
                gpt_notes.append(f"⚠️ GPT не рекомендує купувати {sym}")
        top_tokens = filtered_tokens

    # If GPT forecast is available but we already have buy candidates,
    # ignore the GPT buy list to avoid skipping viable tokens
    if gpt_forecast and not top_tokens:
        allowed = set(gpt_forecast.get("recommend_buy", []))
        filtered = []
        for pair, data in all_buy_tokens:
            sym = pair.replace("USDT", "")
            if allowed and sym not in allowed:
                continue
            filtered.append((pair, data))
        top_tokens = filtered
        filtered_tokens = filtered

    if len(top_tokens) < 3 and all_buy_tokens:
        # Force buy top-3 tokens by basic score even if filtered out
        fallback = sorted(
            all_buy_tokens,
            key=lambda x: x[1].get("prob_up", 0) * x[1].get("expected_profit", 0),
            reverse=True,
        )[:3]
        for pair, data in fallback:
            if pair not in [p for p, _ in top_tokens]:
                top_tokens.append((pair, data))
                logger.warning(f"[dev] ⚠️ Куплено попри фільтр: {pair.replace('USDT','')} у топ‑3 BUY")
        filtered_tokens = top_tokens

    if len(top_tokens) < 3:
        logger.info("[dev] Недостатньо BUY токенів з високим score, використовую найкращі з усього BUY списку.")
        top_tokens = all_buy_tokens[:3]
    if not top_tokens:
        return [], [], [], [], [], "", gpt_forecast

    best_pair, best_data = top_tokens[0]

    low_profit = False
    if best_data.get('expected_profit') <= CONVERSION_MIN_EXPECTED_PROFIT:
        logger.info(
            "Low expected profit %.4f USDT for %s",
            best_data.get('expected_profit'),
            best_pair,
        )
        low_profit = True

    signals: List[Dict[str, float]] = []
    for asset, amount in portfolio.items():
        pair = asset if asset.endswith("USDT") else f"{asset}USDT"
        current = predictions.get(pair)
        if not current:
            continue
        if best_data.get('expected_profit') <= current.get('expected_profit'):
            continue

        from_price = current.get('price')
        from_usdt = amount * from_price
        to_qty = from_usdt / best_data.get('price')
        diff = best_data.get('expected_profit') - current.get('expected_profit')
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
                "tp": best_data.get('tp'),
                "sl": best_data.get('sl'),
                "score": best_data.get("score", 0.0),
                "rrr": best_data.get("risk_reward_ratio", 0.0),
                "price": best_data.get('price'),
                "expected_profit": best_data.get("expected_profit", 0.0),
                "prob_up": best_data.get("prob_up", 0.0),
                "ml_proba": float(best_data.get("ml_proba", 0.5)),
                "from_price": from_price,
                "from_expected_profit": current.get("expected_profit", 0.0),
                "from_prob_up": current.get("prob_up", 0.0),
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
                portfolio_pairs, key=lambda x: x[1] * x[2].get("price")
            )
            from_amount = amount * 0.9
            from_price = current.get('price')
            from_usdt = from_amount * from_price
            to_qty = from_usdt / best_data.get('price')
            diff = best_data.get('expected_profit') - current.get('expected_profit')
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
                    "tp": best_data.get('tp'),
                    "sl": best_data.get('sl'),
                    "score": best_data.get("score", 0.0),
                    "rrr": best_data.get("risk_reward_ratio", 0.0),
                    "price": best_data.get('price'),
                    "expected_profit": best_data.get("expected_profit", 0.0),
                    "prob_up": best_data.get("prob_up", 0.0),
                    "ml_proba": float(best_data.get("ml_proba", 0.5)),
                    "from_price": from_price,
                    "from_expected_profit": current.get("expected_profit", 0.0),
                    "from_prob_up": current.get("prob_up", 0.0),
                }
            )

    to_buy = [p.replace("USDT", "") for p, _ in top_tokens]
    sell_candidates: list[str] = []
    for symbol, amount in portfolio.items():
        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        pred = predictions.get(pair)
        if not pred:
            continue
        prob = pred.get("prob_up", 0.0)
        ep = pred.get("expected_profit", 0.0)
        score = prob * ep
        if score < 0.01:
            sell_candidates.append(symbol)
        else:
            logger.info("[dev] Пропущено %s — prob_up=%.2f, exp=%.2f", symbol, prob, ep)

    if not sell_candidates:
        logger.warning(
            "[dev] ⚠️ Немає токенів для продажу — пробуємо fallback: продаємо найдешевші/нерухомі активи"
        )
        sorted_portfolio = sorted(portfolio.items(), key=lambda x: x[1])
        for symbol, amount in sorted_portfolio:
            if symbol in predictions and amount > 0:
                sell_candidates.append(symbol)
            if len(sell_candidates) >= 3:
                break

    to_sell = sell_candidates
    summary = [f"{p.replace('USDT', '')}: {d.get('expected_profit'):.2f}" for p, d in top_tokens]
    report_text = f"USDT balance: {balances.get('USDT', 0.0)}\n" + "\n".join(summary)

    return (
        signals,
        to_buy,
        to_sell,
        filtered_tokens,
        summary,
        report_text,
        gpt_forecast,
        predictions,
    )


def sell_unprofitable_assets(
    portfolio: Dict[str, float],
    predictions: Dict[str, Dict[str, float]],
    gpt_forecast: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """Sell all assets that are not in the top-3 by expected profit."""

    if not portfolio or not predictions:
        return []

    top3 = sorted(
        predictions.items(),
        key=lambda x: x[1].get("expected_profit", 0.0),
        reverse=True,
    )[:3]
    top3_symbols = {p.replace("USDT", "") for p, _ in top3}

    sold_tokens = []

    to_sell = [
        token for token in portfolio if token != "USDT" and token not in top3_symbols
    ]

    for token in to_sell:
        amount = portfolio.get(token, 0.0)
        if amount <= 0:
            continue
        pair = token if token.endswith("USDT") else f"{token}USDT"
        logger.info(f"[dev] SELL: {pair}, кількість: {amount}")
        result = market_sell(pair, amount)
        if result.get("status") == "success":
            logger.info(f"[dev] Продано {amount} {token}")
            TRADE_SUMMARY.get('sold').append(f"{token} ({amount:.6f})")
            sold_tokens.append(token)
        elif result.get("status") == "converted":
            logger.info(f"[dev] Сконвертовано {amount} {token}")
            sold_tokens.append(token)
        else:
            reason = result.get("message", "невідома помилка")
            logger.warning(
                f"[dev] ⚠️ Не вдалося продати або сконвертувати {token}: {reason}"
            )

    if not sold_tokens:
        logger.info("[dev] Нічого не продано")

    return sold_tokens


def convert_portfolio_to_usdt(portfolio: Dict[str, float]) -> list[str]:
    """Convert all assets in ``portfolio`` to USDT using Binance Convert."""

    converted: list[str] = []
    for asset, amount in portfolio.items():
        if asset in {"USDT", "BUSD"} or amount <= 0:
            continue
        result = convert_to_usdt(asset, amount)
        if result and result.get("status") != "error":
            logger.info(
                f"[dev] Конвертовано {amount} {asset} у USDT"
            )
            TRADE_SUMMARY.get('sold').append(f"{asset} ({amount:.6f})")
            converted.append(asset)
        else:
            logger.warning(
                f"[dev] ⚠️ Не вдалося конвертувати {asset}: {result}"
            )

    if not converted:
        logger.warning("[dev] ❌ Жоден актив не вдалося конвертувати в USDT")

    return converted


def _compose_failure_message(
    portfolio: Dict[str, float],
    predictions: Dict[str, Dict[str, float]],
    usdt_balance: float,
    *,
    identical_profits: bool = False,
) -> str:
    """Return concise explanation why no trade was executed."""

    reasons: list[str] = []
    if not portfolio:
        reasons.append("немає активів для продажу")
    if usdt_balance <= 0:
        reasons.append("баланс USDT = 0")
    if not predictions:
        reasons.append("немає сигналів для купівлі")
    if identical_profits:
        reasons.append("усі пари мають однаковий expected_profit")
    if not reasons:
        reasons.append("ринок занадто слабкий")

    return f"[dev] Без угод: {'; '.join(reasons)}."

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
) -> tuple[list[str], list[str]]:
    if not signals:
        logger.info("No conversion signals generated")
        message = _compose_failure_message(portfolio or {}, predictions or {}, usdt_balance, identical_profits=identical_profits)
        await send_messages(int(chat_id), [message])
        return [], []

    lines = []
    summary = [f"[dev] Куплено {len(signals)} токен{'и' if len(signals) != 1 else ''}:"]
    sold: list[str] = []
    bought: list[str] = []

    for s in signals:
        precision = get_symbol_precision(f"{s.get('to_symbol')}USDT")
        precision = max(2, min(4, precision))
        to_qty = s.get('to_amount')
        to_amount = _human_amount(to_qty, precision)
        result = try_convert(s.get('from_symbol'), s.get('to_symbol'), s.get('from_amount'))
        if result and result.get("orderId"):
            lines.append(
                f"✅ Конвертовано {s.get('from_symbol')} → {s.get('to_symbol')}\nFROM: {s.get('from_amount'):.4f}\nTO: ≈{to_amount}\nML={s.get('ml_proba'):.2f}, exp={s.get('expected_profit'):.2f}, RRR={s.get('rrr', 0):.2f}, score={s.get('score', 0):.2f}"
            )
            sold.append(f"- {s.get('from_amount')}{s.get('from_symbol')} → {s.get('to_symbol')}")
            bought.append(f"- {to_amount} {s.get('to_symbol')} (score: {s.get('score'):.2f}, expected_profit: {s.get('expected_profit'):.2f})")
        else:
            reason = result.get("message", "невідома помилка") if result else "невідома помилка"
            lines.append(f"❌ Не вдалося конвертувати {s.get('from_symbol')} → {s.get('to_symbol')}\nПричина: {reason}")

    text = "\n\n".join(lines)
    messages = list(split_telegram_message("\n".join(summary), 4000))
    messages.extend(split_telegram_message(text, 4000))
    last_file = os.path.join("logs", "last_conversion_hash.txt")
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    last_hash = None
    if os.path.exists(last_file):
        with open(last_file, "r", encoding="utf-8") as f:
            last_hash = f.read().strip() or None

    if text_hash == last_hash:
        if low_profit:
            messages.append("⚠️ Очікуваний прибуток низький")
        if gpt_notes:
            messages.extend(gpt_notes)
        await send_messages(int(chat_id), messages)
        return sold, bought

    try:
        os.makedirs(os.path.dirname(last_file), exist_ok=True)
        with open(last_file, "w", encoding="utf-8") as f:
            f.write(text_hash)
    except OSError as exc:
        logger.warning("Could not persist %s: %s", last_file, exc)

    TRADE_SUMMARY.get('sold').extend(sold)
    TRADE_SUMMARY.get('bought').extend(bought)
    await send_messages(int(chat_id), messages)
    return sold, bought


async def buy_with_remaining_usdt(
    usdt_balance: float,
    top_tokens: List[tuple[str, Dict[str, float]]],
    *,
    chat_id: int,
    gpt_forecast: Optional[Dict[str, List[str]]] = None,
) -> Optional[str]:
    """Buy the best available token with the remaining USDT balance."""

    if usdt_balance <= 0:
        logger.warning("[dev] ⚠️ Купівля неможлива — баланс USDT = 0")
        return None
    logger.info("[dev] Купівля на залишок: top_tokens = %s", top_tokens)
    tried_tokens = [p for p, _ in top_tokens]
    if not top_tokens:
        logger.warning("[dev] ⚠️ Купівля: top_tokens порожній — fallback на top-1.")
        try:
            predictions = load_predictions()
        except Exception:  # pragma: no cover - diagnostics only
            predictions = {}
        fallback = filter_top_tokens(predictions, limit=1, gpt_forecast=gpt_forecast)
        if not fallback:
            logger.warning("[dev] ❌ Після фільтрації жодного токена — не буде купівлі")
            return None
        top_tokens = [t for t in fallback if t[0] not in tried_tokens]

    for pair, data in top_tokens:
        symbol = pair.replace("USDT", "")
        price = get_symbol_price(pair)
        if price <= 0:
            continue
        step = get_lot_step(pair)
        qty = usdt_balance / price
        qty = round_step_size(qty, step)
        min_notional = get_min_notional(pair)
        notional = qty * price
        if notional < min_notional:
            logger.warning(
                "[dev] ⛔ Пропущено %s — занадто малий обсяг (%.2f < %.2f)",
                symbol,
                notional,
                min_notional,
            )
            continue

        logger.info(
            "[dev] Перевірка: %s — qty=%.6f, price=%.6f, notional=%.6f, min_notional=%.6f",
            symbol,
            qty,
            price,
            notional,
            min_notional,
        )
        logger.info("[dev] Купівля на залишок: %s — qty=%.6f price=%.6f", symbol, qty, price)
        result = market_buy_symbol_by_amount(symbol, usdt_balance)

        if result and result.get("status") == "success":
            TRADE_SUMMARY.get('bought').append(
                f"Залишок → {symbol} на {usdt_balance:.2f}"
            )
            return symbol
        else:
            logger.warning(
                "[dev] ❗ Купівля на залишок %s не вдалася: %s",
                symbol,
                result,
            )
            continue

    logger.warning(
        "[dev] ❌ Не вдалося купити жоден токен — завершення циклу"
    )
    logger.warning("[dev] ❌ Нічого не куплено — завершення трейд-циклу")
    return None


async def main(chat_id: int) -> dict:
    """Simplified auto-trade cycle relying on daily predictions."""

    from constants import TRADE_SUMMARY
    TRADE_SUMMARY.setdefault("sold", [])
    TRADE_SUMMARY.setdefault("bought", [])
    TRADE_SUMMARY.setdefault("errors", [])

    TRADE_SUMMARY.get('sold').clear()
    TRADE_SUMMARY.get('bought').clear()
    TRADE_SUMMARY.get('errors').clear()

    try:
        from daily_analysis import generate_zarobyty_report

        _, _, _, _, predictions = await generate_zarobyty_report()
    except Exception as exc:  # pragma: no cover - fallback to cache
        logger.warning("[dev] run_daily_analysis failed: %s", exc)
        predictions = load_predictions()

    gpt_forecast = load_gpt_filters()
    top_tokens = filter_top_tokens(predictions, limit=3, gpt_forecast=gpt_forecast)

    balances = get_binance_balances()
    usdt_before = balances.get("USDT", 0.0)
    logger.info("[dev] Баланс USDT перед трейдом: %.4f", usdt_before)
    logger.info("[dev] Портфель: %s", balances)
    usdt_balance = usdt_before
    portfolio_tokens = [
        t for t in balances if t != "USDT" and f"{t}USDT" in VALID_PAIRS
    ]

    # 1. Buy if only USDT is available
    if usdt_balance > 0 and not portfolio_tokens:
        await buy_with_remaining_usdt(
            usdt_balance,
            top_tokens,
            chat_id=chat_id,
            gpt_forecast=gpt_forecast,
        )
        logger.info("[dev] TRADE_SUMMARY: %s", TRADE_SUMMARY)
        after = get_binance_balances().get("USDT", 0.0)
        logger.info("[dev] Баланс USDT після трейду: %.4f", after)
        return {
            "sold": TRADE_SUMMARY.get('sold'),
            "bought": TRADE_SUMMARY.get('bought'),
            "before": usdt_before,
            "after": after,
        }

    # 2. Sell portfolio assets then buy with the updated USDT balance
    if usdt_balance > 0 and portfolio_tokens:
        sell_unprofitable_assets(balances, predictions, gpt_forecast)
        # 🟢 Купити після продажу (оновлений баланс)
        updated_balances = get_binance_balances()
        await buy_with_remaining_usdt(
            updated_balances.get("USDT", 0.0),
            top_tokens,
            chat_id=chat_id,
            gpt_forecast=gpt_forecast,
        )
        logger.info("[dev] TRADE_SUMMARY: %s", TRADE_SUMMARY)
        if "update_binance_cache" in globals():
            try:
                update_binance_cache()  # type: ignore[func-returns-value]
            except Exception as exc:  # pragma: no cover - optional
                logger.warning("[dev] update_binance_cache failed: %s", exc)
        balances = get_binance_balances()
        usdt_balance = balances.get("USDT", 0.0)
        await buy_with_remaining_usdt(
            usdt_balance,
            top_tokens,
            chat_id=chat_id,
            gpt_forecast=gpt_forecast,
        )
        logger.info("[dev] TRADE_SUMMARY: %s", TRADE_SUMMARY)
        after = get_binance_balances().get("USDT", 0.0)
        logger.info("[dev] Баланс USDT після трейду: %.4f", after)
        return {
            "sold": TRADE_SUMMARY.get('sold'),
            "bought": TRADE_SUMMARY.get('bought'),
            "before": usdt_before,
            "after": after,
        }

    # 3. Sell or convert assets if no USDT balance
    if usdt_balance == 0 and portfolio_tokens:
        sold = sell_unprofitable_assets(balances, predictions, gpt_forecast)
        if not sold:
            logger.warning(
                "[dev] \ud83d\udca4 Нічого не продано. Спробуємо конвертацію в USDT."
            )
            sold = convert_portfolio_to_usdt(balances)
        if "update_binance_cache" in globals():
            try:
                update_binance_cache()  # type: ignore[func-returns-value]
            except Exception as exc:  # pragma: no cover - optional
                logger.warning("[dev] update_binance_cache failed: %s", exc)
        balances = get_binance_balances()
        usdt_balance = balances.get("USDT", 0.0)
        if usdt_balance > 0:
            await buy_with_remaining_usdt(
                usdt_balance,
                top_tokens,
                chat_id=chat_id,
                gpt_forecast=gpt_forecast,
            )
            logger.info("[dev] TRADE_SUMMARY: %s", TRADE_SUMMARY)

    after = get_binance_balances().get("USDT", 0.0)
    logger.info("[dev] Баланс USDT після трейду: %.4f", after)
    return {
        "sold": TRADE_SUMMARY.get('sold'),
        "bought": TRADE_SUMMARY.get('bought'),
        "before": usdt_before,
        "after": after,
    }


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main(0))
