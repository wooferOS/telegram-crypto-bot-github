from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

from convert_logger import logger

# Load local quote limits if available
try:
    with open("quote_limits.json", "r", encoding="utf-8") as f:
        quote_limits = json.load(f)
except FileNotFoundError:
    quote_limits = {}

from convert_api import (
    get_quote_with_retry,
    accept_quote,
    get_balances,
    is_convertible_pair,
    get_available_to_tokens,
    get_min_convert_amount,
    load_quote_limits,
    save_quote_limits,
    is_within_quote_limits,
)
from binance_api import get_binance_balances, get_spot_price, get_ratio
from convert_notifier import (
    notify_success,
    notify_failure,
    notify_no_trade,
    notify_fallback_trade,
)
import convert_notifier
from convert_filters import passes_filters, MIN_SCORE
from convert_logger import (
    save_convert_history,
    log_prediction,
    log_quote_skipped,
    log_conversion_success,
    log_conversion_error,
    log_skipped_quotes,
    log_conversion_result,
)
from quote_counter import should_throttle, reset_cycle
from convert_model import _hash_token, get_top_token_pairs

FALLBACK_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "fallback_history.json")
HISTORY_PATH = os.path.join("logs", "convert_history.json")

MIN_NOTIONAL_USDT = 0.5
MIN_NOTIONAL = MIN_NOTIONAL_USDT


def min_notional(token: str) -> float:
    """Return minimal tradable amount for a token based on USDT value."""
    price = get_spot_price(token)
    if price:
        return MIN_NOTIONAL_USDT / price
    return 0.0


def _load_fallback_history() -> Dict[str, Any]:
    if not os.path.exists(FALLBACK_HISTORY_PATH):
        return {}
    try:
        with open(FALLBACK_HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # pragma: no cover - file issues
        logger.warning(f"[dev3] failed to read fallback history: {exc}")
        return {}


def _save_fallback_history(from_token: str, to_token: str) -> None:
    data = {
        "last_from": from_token,
        "last_to": to_token,
        "timestamp": datetime.utcnow().isoformat(),
    }
    try:
        with open(FALLBACK_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as exc:  # pragma: no cover - file issues
        logger.warning(f"[dev3] failed to write fallback history: {exc}")


def has_successful_trade(from_token: str) -> bool:
    """Return True if there is a successful executed trade for from_token."""
    if not os.path.exists(HISTORY_PATH):
        return False
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return False
    for r in history:
        value = r.get("value", r)
        if (
            value.get("from_token") == from_token
            and value.get("executed")
        ):
            return True
    return False


MAX_QUOTES_PER_CYCLE = 20
MAX_QUOTES_PER_TOKEN = 5
TOP_N_PAIRS = 10


def try_convert(from_token: str, to_token: str, amount: float, score: float) -> bool:
    """Attempt a single conversion and log the result."""
    logger.info(
        f"🔁 Починаємо конверсію: {from_token} → {to_token} з amount={amount}"
    )
    log_prediction(from_token, to_token, score)
    if amount <= 0:
        log_quote_skipped(from_token, to_token, "no_balance")
        return False

    if amount < min_notional(from_token):
        logger.info(
            f"⛔️ Недостатньо {from_token}: {amount} < {min_notional(from_token)}"
        )
        return False

    from_token_price = get_spot_price(from_token)
    if from_token_price:
        usd_value = amount * from_token_price
        if usd_value < MIN_NOTIONAL:
            logger.info(
                f"⛔️ Пропуск {from_token} — баланс занизький (≈{usd_value:.4f} USDT), minNotional={MIN_NOTIONAL}"
            )
            return False

    if should_throttle(from_token, to_token):
        log_quote_skipped(from_token, to_token, "throttled")
        return False

    if not is_convertible_pair(from_token, to_token):
        logger.info(
            f"[dev3] ❌ Пара {from_token} → {to_token} недоступна для конвертації — пропущено"
        )
        return False

    if not is_within_quote_limits(from_token, to_token, amount, quote_limits):
        msg = f"⛔ Пропускаємо {from_token} → {to_token}: {amount} поза межами ліміту"
        with open("logs/convert_debug.log", "a") as f:
            f.write(msg + "\n")
        logger.info(msg)
        return False

    min_amount = get_min_convert_amount(from_token, to_token)
    if amount < min_amount:
        logger.warning(
            f"⚠️ Пропуск {from_token} → {to_token}: amount={amount} < min={min_amount}"
        )
        return False

    quote = get_quote_with_retry(from_token, to_token, amount, quote_limits)
    if not quote or quote.get("price") is None:
        logger.warning(
            f"⛔️ Пропуск {from_token} → {to_token}: quote.price is None після всіх спроб"
        )
        logger.error(
            f"[FATAL] Не вдалося отримати жоден quote для {from_token} → {to_token}"
        )
        log_quote_skipped(from_token, to_token, "invalid_quote")
        return False

    amount_data = quote.get("amount", 0.0)
    if isinstance(amount_data, dict):
        amount = amount_data.get("from", 0.0)
    else:
        amount = amount_data
    logger.info(f"[dev3] Quote amount: {amount}")

    if float(quote.get("toAmount", 0)) < min_notional(to_token):
        logger.info(
            f"❌ Недостатній обсяг TO: {quote.get('toAmount')} < {min_notional(to_token)}"
        )
        return False

    valid, reason = passes_filters(score, quote, amount)
    if not valid:
        logger.info(
            f"[dev3] \u26d4\ufe0f Пропуск {from_token} → {to_token}: score={score:.4f}, причина={reason}, quote={quote}"
        )
        return False

    resp = accept_quote(quote) if quote else None
    log_conversion_result(quote, accepted=bool(resp and resp.get("success") is True))
    if resp and resp.get("success") is True:
        profit = float(resp.get("toAmount", 0)) - float(resp.get("fromAmount", 0))
        log_conversion_success(from_token, to_token, profit)
        notify_success(
            from_token,
            to_token,
            float(resp.get("fromAmount", 0)),
            float(resp.get("toAmount", 0)),
            score,
            float(quote.get("ratio", 0)) - 1,
        )
        features = [
            float(quote.get("ratio", 0)),
            float(quote.get("inverseRatio", 0)),
            float(amount),
            _hash_token(from_token),
            _hash_token(to_token),
        ]
        save_convert_history(
            {
                "from": from_token,
                "to": to_token,
                "features": features,
                "profit": profit,
                "accepted": True,
            }
        )
        return True

    reason = resp.get("msg") if isinstance(resp, dict) else "Unknown error"
    logger.warning(f"❌ Binance відхилив quote: {resp}")
    log_conversion_error(from_token, to_token, reason)
    notify_failure(from_token, to_token, reason=reason)
    return False


def fallback_convert(pairs: List[Dict[str, Any]], balances: Dict[str, float]) -> None:
    """Attempt fallback conversion using the token with the highest balance."""

    # Choose token with the largest balance excluding stablecoins and delisted tokens
    candidates = [
        (token, amt)
        for token, amt in balances.items()
        if amt > 0 and token not in ("USDT", "AMB", "DELISTED")
    ]
    fallback_token = max(candidates, key=lambda x: x[1], default=(None, 0.0))[0]

    if not fallback_token:
        logger.warning(
            "🔹 [FALLBACK] Не знайдено жодного токена з балансом для fallback"
        )
        return

    valid_to_tokens = [
        p
        for p in pairs
        if p.get("from_token") == fallback_token and float(p.get("score", 0)) > 0
    ]

    if not valid_to_tokens:
        logger.warning(
            f"🔹 [FALLBACK] Актив '{fallback_token}' з найбільшим балансом не сконвертовано"
        )
        logger.warning(
            "🔸 Причина: не знайдено жодного валідного `to_token` для fallback (score недостатній або немає прогнозу)"
        )
        return

    # Load last successful fallback conversion in order to detect cyclic calls
    history = _load_fallback_history()
    last_from = history.get("last_from")
    last_to = history.get("last_to")
    last_ts = history.get("timestamp")
    last_dt = None
    if last_from and last_to and last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts)
        except ValueError:
            last_dt = None

    valid_to_tokens.sort(key=lambda x: x.get("score", 0), reverse=True)

    selected_pair = None
    for pair in valid_to_tokens:
        candidate = pair.get("to_token")
        skip = False
        if last_dt:
            if (
                candidate == last_to
                and fallback_token == last_from
                and datetime.utcnow() - last_dt < timedelta(hours=24)
            ):
                # same pair recently used
                skip = True
            elif (
                candidate == last_from
                and fallback_token == last_to
                and datetime.utcnow() - last_dt < timedelta(hours=24)
            ):
                logger.warning(
                    f"🔁 [FALLBACK] Виявлено циклічну конверсію: {fallback_token} → {candidate}. Пропускаємо."
                )
                skip = True
        if skip:
            continue
        selected_pair = pair
        break

    if not selected_pair:
        logger.warning(
            "⚠️ [FALLBACK] Всі токени відкинуто через недавню циклічну активність"
        )
        return

    selected_to_token = selected_pair.get("to_token")
    amount = balances.get(fallback_token, 0.0)
    logger.info(
        f"🔄 [FALLBACK] Спроба конвертації {fallback_token} → {selected_to_token}"
    )

    success = try_convert(
        fallback_token,
        selected_to_token,
        amount,
        float(selected_pair.get("score", 0)),
    )
    if not success:
        logger.info(
            f"🔹 [FALLBACK] Конверсія {fallback_token} → {selected_to_token} не виконана"
        )
    else:
        _save_fallback_history(fallback_token, selected_to_token)


def _load_top_pairs() -> List[Dict[str, Any]]:
    path = os.path.join(os.path.dirname(__file__), "top_tokens.json")
    if not os.path.exists(path):
        logger.warning("[dev3] top_tokens.json not found")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data:
            pairs_str = ", ".join(
                f"{p.get('from_token')} → {p.get('to_token')}" for p in data
            )
            logger.info(f"[dev3] 🧠 Загружено top_tokens для аналізу: {pairs_str}")
        else:
            logger.info("[dev3] 🧠 Загружено top_tokens для аналізу: <empty>")
        return data
    except Exception as exc:  # pragma: no cover - file issues
        logger.warning("[dev3] failed to read top_tokens.json: %s", exc)
        return []


def process_top_pairs(pairs: List[Dict[str, Any]] | None = None) -> None:
    """Process token pairs and attempt conversions."""
    reset_cycle()
    load_quote_limits()
    quote_counter = 0
    MAX_QUOTES_PER_CYCLE = 20
    if pairs is None:
        pairs = _load_top_pairs()
    balances = get_balances()

    if not pairs:
        logger.warning("[dev3] No pairs to process")
        non_zero = {t: a for t, a in balances.items() if a > 0 and t != "USDT"}
        if len(non_zero) == 1:
            from_token = max(non_zero, key=non_zero.get)
            amount = non_zero[from_token]
            to_tokens = get_available_to_tokens(from_token)
            best_to = None
            best_profit = float("-inf")
            for tgt in to_tokens:
                ratio = get_ratio(from_token, tgt)
                profit = ratio - 1.0
                if profit > best_profit:
                    best_profit = profit
                    best_to = tgt

            if best_to:
                quote = get_quote_with_retry(from_token, best_to, amount, quote_limits)
                if quote:
                    resp = accept_quote(quote)
                    log_conversion_result(
                        quote, accepted=bool(resp and resp.get("success") is True)
                    )
                    if resp and resp.get("success") is True:
                        convert_notifier.fallback_triggered = (from_token, best_to)
                        profit = float(resp.get("toAmount", 0)) - float(
                            resp.get("fromAmount", 0)
                        )
                        log_conversion_success(from_token, best_to, profit)
                        notify_success(
                            from_token,
                            best_to,
                            float(resp.get("fromAmount", 0)),
                            float(resp.get("toAmount", 0)),
                            best_profit,
                            float(quote.get("ratio", 0)) - 1,
                        )
                        notify_fallback_trade(from_token, best_to, best_profit, amount)
                        features = [
                            float(quote.get("ratio", 0)),
                            float(quote.get("inverseRatio", 0)),
                            float(amount),
                            _hash_token(from_token),
                            _hash_token(best_to),
                        ]
                        save_convert_history(
                            {
                                "from": from_token,
                                "to": best_to,
                                "features": features,
                                "profit": profit,
                                "accepted": True,
                            }
                        )
                        save_quote_limits()
                        with open("quote_limits.json", "w", encoding="utf-8") as f:
                            json.dump(quote_limits, f, indent=2)
                        return
        notify_no_trade(max(balances, key=balances.get), len(pairs), 0.0)
        save_quote_limits()
        with open("quote_limits.json", "w", encoding="utf-8") as f:
            json.dump(quote_limits, f, indent=2)
        return

    pairs_by_from: Dict[str, List[Dict[str, Any]]] = {}
    for p in pairs:
        f = p.get("from_token")
        t = p.get("to_token")
        if not f or not t:
            continue
        score = float(p.get("score", 0))
        prob_up = float(p.get("prob_up", 0))
        forecast_count = int(p.get("forecast_count", 0))
        pairs_by_from.setdefault(f, []).append({
            "to_token": t,
            "score": score,
            "prob_up": prob_up,
            "forecast_count": forecast_count,
        })

    for lst in pairs_by_from.values():
        lst.sort(key=lambda x: x["score"], reverse=True)

    successful_conversions = False

    for from_token in pairs_by_from:
        quotes_used = 0
        amount = balances.get(from_token, 0.0)
        if amount <= 0:
            continue
        if amount < min_notional(from_token):
            logger.info(
                f"⛔️ Недостатньо {from_token}: {amount} < {min_notional(from_token)}"
            )
            continue

        to_candidates = pairs_by_from.get(from_token, [])
        if not to_candidates:
            logger.info(f"[dev3] ⛔️ {from_token} пропущено — не входить до GPT-прогнозу")
            continue

        for entry in to_candidates:
            if quotes_used >= MAX_QUOTES_PER_TOKEN:
                logger.info(
                    f"[dev3] ⏩ Досягнуто ліміту {MAX_QUOTES_PER_TOKEN} quote для {from_token}"
                )
                break
            to_token = entry["to_token"]
            score = entry["score"]
            prob_up = float(entry.get("prob_up", 0))
            forecast_count = int(entry.get("forecast_count", 0))

            allow_learning_trade = False
            if (
                score == 0.0
                and prob_up == 0.0
                and forecast_count > 50
                and not has_successful_trade(from_token)
            ):
                allow_learning_trade = True

            if score < MIN_SCORE and not allow_learning_trade:
                continue

            if allow_learning_trade:
                msg = (
                    f"[dev3] 🤖 Навчальний трейд для {from_token} → {to_token} (score = {score:.2f})"
                )
                logger.info(msg)
                convert_notifier.send_telegram(msg)

            log_prediction(from_token, to_token, score)
            logger.info(
                f"🔁 Починаємо конверсію: {from_token} → {to_token} з amount={amount}"
            )

            if should_throttle(from_token, to_token):
                log_quote_skipped(from_token, to_token, "throttled")
                continue

            from_token_price = get_spot_price(from_token)
            if from_token_price:
                usd_value = amount * from_token_price
                if usd_value < MIN_NOTIONAL:
                    logger.info(
                        f"⛔️ Пропуск {from_token} — баланс занизький (≈{usd_value:.4f} USDT), minNotional={MIN_NOTIONAL}"
                    )
                    continue

            if quote_counter >= MAX_QUOTES_PER_CYCLE:
                logger.warning(f"[dev3] 🚫 Досягнуто ліміту {MAX_QUOTES_PER_CYCLE} quote-запитів у цьому циклі")
                save_quote_limits()
                with open("quote_limits.json", "w", encoding="utf-8") as f:
                    json.dump(quote_limits, f, indent=2)
                return
            quote_counter += 1
            quotes_used += 1
            min_amount = get_min_convert_amount(from_token, to_token)
            if amount < min_amount:
                logger.warning(
                    f"⚠️ Пропуск {from_token} → {to_token}: amount={amount} < min={min_amount}"
                )
                continue
            quote = get_quote_with_retry(from_token, to_token, amount, quote_limits)
            if not quote or quote.get("price") is None:
                logger.warning(
                    f"⛔️ Пропуск {from_token} → {to_token}: quote.price is None після всіх спроб"
                )
                log_quote_skipped(from_token, to_token, "invalid_quote")
                continue

            if float(quote.get("toAmount", 0)) < min_notional(to_token):
                logger.info(
                    f"❌ Недостатній обсяг TO: {quote.get('toAmount')} < {min_notional(to_token)}"
                )
                continue

            resp = accept_quote(quote)
            log_conversion_result(
                quote, accepted=bool(resp and resp.get("success") is True)
            )

            if resp and resp.get("success") is True:
                logger.info(
                    f"✅ Успішна конверсія: {from_token} → {to_token}, сума: {amount}, score: {score}"
                )
                profit = float(resp.get("toAmount", 0)) - float(
                    resp.get("fromAmount", 0)
                )
                log_conversion_success(from_token, to_token, profit)
                notify_success(
                    from_token,
                    to_token,
                    float(resp.get("fromAmount", 0)),
                    float(resp.get("toAmount", 0)),
                    score,
                    float(quote.get("ratio", 0)) - 1,
                )
                features = [
                    float(quote.get("ratio", 0)),
                    float(quote.get("inverseRatio", 0)),
                    float(amount),
                    _hash_token(from_token),
                    _hash_token(to_token),
                ]
                save_convert_history(
                    {
                        "from": from_token,
                        "to": to_token,
                        "features": features,
                        "profit": profit,
                        "accepted": True,
                    }
                )
                successful_conversions = True
                break
            else:
                err = resp.get("msg") if isinstance(resp, dict) else "Unknown error"
                logger.info(f"❌ Помилка accept_quote: {err}")
                log_conversion_error(from_token, to_token, err)
                notify_failure(from_token, to_token, reason=err)
        if successful_conversions:
            break
    if not successful_conversions:
        logger.info("[dev3] ❌ Жодна пара не була конвертована")
        balances = get_binance_balances()
        non_zero = [t for t, a in balances.items() if a > 0 and t != "USDT"]
        if len(non_zero) == 1:
            fallback_token = non_zero[0]
            candidates = [
                p
                for p in pairs
                if p.get("from_token") == fallback_token
            ]
            candidates.sort(key=lambda x: float(x.get("expected_profit", 0)), reverse=True)
            if candidates:
                best = candidates[0]
                to_token = best.get("to_token")
                amount = balances[fallback_token]
                quote = get_quote_with_retry(fallback_token, to_token, amount, quote_limits)
                if quote:
                    resp = accept_quote(quote)
                    log_conversion_result(
                        quote, accepted=bool(resp and resp.get("success") is True)
                    )
                    if resp and resp.get("success") is True:
                        convert_notifier.fallback_triggered = (fallback_token, to_token)
                        profit = float(resp.get("toAmount", 0)) - float(resp.get("fromAmount", 0))
                        log_conversion_success(fallback_token, to_token, profit)
                        notify_success(
                            fallback_token,
                            to_token,
                            float(resp.get("fromAmount", 0)),
                            float(resp.get("toAmount", 0)),
                            float(best.get("score", 0)),
                            float(quote.get("ratio", 0)) - 1,
                        )
                        notify_fallback_trade(
                            fallback_token,
                            to_token,
                            float(best.get("score", 0)),
                            amount,
                        )
                        features = [
                            float(quote.get("ratio", 0)),
                            float(quote.get("inverseRatio", 0)),
                            float(amount),
                            _hash_token(fallback_token),
                            _hash_token(to_token),
                        ]
                        save_convert_history(
                            {
                                "from": fallback_token,
                                "to": to_token,
                                "features": features,
                                "profit": profit,
                                "accepted": True,
                            }
                        )
                        save_quote_limits()
                        with open("quote_limits.json", "w", encoding="utf-8") as f:
                            json.dump(quote_limits, f, indent=2)
                        return
        pred_path = os.path.join("logs", "predictions.json")
        try:
            with open(pred_path, "r", encoding="utf-8") as f:
                preds = json.load(f)
        except Exception:
            preds = []
        best_score = 0.0
        if preds:
            best_score = max(float(p.get("score", 0)) for p in preds)
        from_token = max(balances, key=balances.get) if balances else "?"
        notify_no_trade(from_token, len(preds), best_score)
        save_quote_limits()
        with open("quote_limits.json", "w", encoding="utf-8") as f:
            json.dump(quote_limits, f, indent=2)
    else:
        save_quote_limits()
        with open("quote_limits.json", "w", encoding="utf-8") as f:
            json.dump(quote_limits, f, indent=2)
