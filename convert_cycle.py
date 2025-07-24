from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

from convert_api import (
    get_quote_with_retry,
    accept_quote,
    get_balances,
    is_convertible_pair,
    get_symbol_price,
)
from binance_api import get_binance_balances
from convert_notifier import notify_success, notify_failure
from convert_filters import passes_filters
from convert_logger import (
    logger,
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

MIN_NOTIONAL_USDT = 0.5
MIN_NOTIONAL = MIN_NOTIONAL_USDT


def min_notional(token: str) -> float:
    """Return minimal tradable amount for a token based on USDT value."""
    price = get_symbol_price(token)
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


MAX_QUOTES_PER_CYCLE = 20
TOP_N_PAIRS = 10


def try_convert(from_token: str, to_token: str, amount: float, score: float) -> bool:
    """Attempt a single conversion and log the result."""
    log_prediction(from_token, to_token, score)
    if amount <= 0:
        log_quote_skipped(from_token, to_token, "no_balance")
        return False

    if amount < min_notional(from_token):
        logger.info(
            f"⛔️ Недостатньо {from_token}: {amount} < {min_notional(from_token)}"
        )
        return False

    from_token_price = get_symbol_price(from_token)
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

    quote = get_quote_with_retry(from_token, to_token, amount)
    if not quote or quote.get("price") is None:
        logger.warning(
            f"⛔️ Пропуск {from_token} → {to_token}: quote.price is None після всіх спроб"
        )
        log_quote_skipped(from_token, to_token, "invalid_quote")
        return False

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
    quote_counter = 0
    MAX_QUOTES_PER_CYCLE = 20
    if pairs is None:
        pairs = _load_top_pairs()
    if not pairs:
        logger.warning("[dev3] No pairs to process")
        return

    balances = get_balances()

    pairs_by_from: Dict[str, List[Dict[str, Any]]] = {}
    for p in pairs:
        f = p.get("from_token")
        t = p.get("to_token")
        if not f or not t:
            continue
        score = float(p.get("score", 0))
        pairs_by_from.setdefault(f, []).append({"to_token": t, "score": score})

    for lst in pairs_by_from.values():
        lst.sort(key=lambda x: x["score"], reverse=True)

    for from_token in pairs_by_from:
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
            to_token = entry["to_token"]
            score = entry["score"]

            log_prediction(from_token, to_token, score)

            if should_throttle(from_token, to_token):
                log_quote_skipped(from_token, to_token, "throttled")
                continue

            from_token_price = get_symbol_price(from_token)
            if from_token_price:
                usd_value = amount * from_token_price
                if usd_value < MIN_NOTIONAL:
                    logger.info(
                        f"⛔️ Пропуск {from_token} — баланс занизький (≈{usd_value:.4f} USDT), minNotional={MIN_NOTIONAL}"
                    )
                    continue

            if quote_counter >= MAX_QUOTES_PER_CYCLE:
                logger.warning(f"[dev3] 🚫 Досягнуто ліміту {MAX_QUOTES_PER_CYCLE} quote-запитів у цьому циклі")
                return
            quote_counter += 1
            quote = get_quote_with_retry(from_token, to_token, amount)
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
                return
            else:
                err = resp.get("msg") if isinstance(resp, dict) else "Unknown error"
                logger.info(f"❌ Помилка accept_quote: {err}")
                log_conversion_error(from_token, to_token, err)
                notify_failure(from_token, to_token, reason=err)

    logger.info("[dev3] ❌ Жодна пара не була конвертована")
