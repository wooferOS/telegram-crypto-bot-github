from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

from convert_api import (
    get_quote,
    accept_quote,
    get_balances,
    is_convertible_pair,
)
from binance_api import get_binance_balances
from convert_notifier import notify_success, notify_failure, notify_all_skipped
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

    if should_throttle(from_token, to_token):
        log_quote_skipped(from_token, to_token, "throttled")
        return False

    if not is_convertible_pair(from_token, to_token):
        logger.info(
            f"[dev3] ❌ Пара {from_token} → {to_token} недоступна для конвертації — пропущено"
        )
        return False

    quote = get_quote(from_token, to_token, amount)
    if not quote:
        log_quote_skipped(from_token, to_token, "invalid_quote")
        return False

    valid, reason = passes_filters(score, quote, amount)
    if not valid:
        logger.info(
            f"[dev3] \u26d4\ufe0f Пропуск {from_token} → {to_token}: score={score:.4f}, причина={reason}, quote={quote}"
        )
        return False

    quote_id = quote.get("quoteId")
    resp = accept_quote(quote_id) if quote_id else None
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
    """Process top pairs from daily analysis."""
    reset_cycle()
    if pairs is None:
        pairs = _load_top_pairs()
    if not pairs:
        logger.warning("[dev3] No pairs to process")
        return

    top_token_pairs_raw = list(pairs)
    binance_balances = get_binance_balances()
    available_from_tokens = [
        token
        for token, amt in binance_balances.items()
        if amt > 0 and token not in ("USDT", "AMB", "DELISTED")
    ]
    pairs = [p for p in pairs if p.get("from_token") in available_from_tokens]

    if not pairs:
        logger.info(
            "[dev3] ❌ Жодна з пар top_tokens не пройшла: немає балансу для FROM"
        )

    balances = get_balances()

    top_pairs = get_top_token_pairs()
    for from_token, to_token in top_pairs:
        try_convert(
            from_token,
            to_token,
            balances.get(from_token, 0.0),
            0.0,
        )

    if not pairs:
        if binance_balances:
            fallback_convert(top_token_pairs_raw, binance_balances)
        else:
            logger.warning("[dev3] No available tokens for fallback")
        return

    pairs.sort(key=lambda x: x.get("score", 0), reverse=True)
    quote_count = 0
    any_successful_conversion = False
    scored_quotes: List[Dict[str, Any]] = []
    filtered_quotes: List[Dict[str, Any]] = []
    accepted_count = 0

    for item in pairs[:TOP_N_PAIRS]:
        if quote_count >= MAX_QUOTES_PER_CYCLE:
            log_skipped_quotes()
            break

        from_token = item.get("from_token")
        to_token = item.get("to_token")
        score = float(item.get("score", 0))
        amount = balances.get(from_token, 0)

        log_prediction(from_token, to_token, score)

        if amount <= 0:
            log_quote_skipped(from_token, to_token, "no_balance")
            continue

        if should_throttle(from_token, to_token):
            log_quote_skipped(from_token, to_token, "throttled")
            continue

        quote = get_quote(from_token, to_token, amount)
        quote_count += 1

        if not quote:
            log_quote_skipped(from_token, to_token, "invalid_quote")
            continue

        valid, reason = passes_filters(score, quote, amount)
        if not valid:
            logger.info(
                f"[dev3] \u26d4\ufe0f Пропуск {from_token} → {to_token}: score={score:.4f}, причина={reason}, quote={quote}"
            )
            filtered_quotes.append(
                {
                    "from_token": from_token,
                    "to_token": to_token,
                    "quote_data": quote,
                    "score": score,
                }
            )
            scored_quotes.append(
                {
                    "from_token": from_token,
                    "to_token": to_token,
                    "score": score,
                    "quote": quote,
                    "skip_reason": reason,
                }
            )
            continue

        quote_id = quote.get("quoteId")
        resp = accept_quote(quote_id) if quote_id else None
        log_conversion_result(
            quote, accepted=bool(resp and resp.get("success") is True)
        )
        if resp and resp.get("success") is True:
            any_successful_conversion = True
            accepted_count += 1
            logger.info("[dev3] ✅ Трейд успішно прийнято Binance")
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
        else:
            reason = resp.get("msg") if isinstance(resp, dict) else "Unknown error"
            logger.warning(
                "[dev3] ❌ Трейд НЕ відбувся: %s → %s. Причина: %s",
                from_token,
                to_token,
                reason,
            )
            log_conversion_error(from_token, to_token, reason)
            notify_failure(from_token, to_token, reason=reason)

    avg = 0.0
    if scored_quotes:
        scores = [float(x.get("score", 0)) for x in scored_quotes]
        avg = sum(scores) / len(scores)
        mn = min(scores)
        mx = max(scores)
        with open("logs/convert_debug.log", "a", encoding="utf-8") as f:
            f.write(
                f"[dev3] \u2705 \u0421\u0435\u0440\u0435\u0434\u043d\u0456\u0439 score={avg:.4f}, \u043c\u0456\u043d\u0456\u043c\u0430\u043b\u044c\u043d\u0438\u0439={mn:.4f}, \u043c\u0430\u043a\u0441\u0438\u043c\u0430\u043b\u044c\u043d\u0438\u0439={mx:.4f}\n"
            )

    if accepted_count == 0 and filtered_quotes:
        filtered_quotes.sort(key=lambda x: x["score"], reverse=True)
        for entry in filtered_quotes[:2]:
            f_token = entry["from_token"]
            t_token = entry["to_token"]
            sc = entry["score"]
            q_data = entry["quote_data"]
            logger.info(
                f"[dev3] 🧪 Навчальна спроба: {f_token} → {t_token}, score={sc:.4f}, пробуємо accept_quote для збору даних"
            )
            with open("logs/convert_train_data.log", "a", encoding="utf-8") as f:
                f.write(
                    f"[dev3] 🧪 Навчальна угода: {f_token} → {t_token}, score={sc:.4f}, quoteId={q_data.get('quoteId')}\n"
                )
            try:
                resp = accept_quote(q_data.get("quoteId"))
                log_conversion_result(q_data, accepted=False)
            except Exception as exc:
                logger.error(f"[dev3] ❌ Помилка навчальної спроби: {exc}")

    if not any_successful_conversion and scored_quotes:
        fallback = next((x for x in scored_quotes if x["score"] > 0), None)

        if fallback:
            log_reason = fallback.get("skip_reason", "no reason")
            logger.info(
                f"[dev3] ⚠️ Жодна пара не пройшла фільтри. Виконуємо fallback-конверсію: {fallback['from_token']} → {fallback['to_token']} (score={fallback['score']:.2f}, причина skip: {log_reason})"
            )
            logger.info(
                f"🔄 [FALLBACK] Спроба конвертації {fallback['from_token']} → {fallback['to_token']}"
            )
            try:
                resp = accept_quote(fallback["quote"].get("quoteId"))
                log_conversion_result(
                    fallback["quote"],
                    accepted=bool(resp and resp.get("success") is True),
                )
            except Exception as e:
                logger.error(f"[dev3] ❌ Помилка під час fallback-конверсії: {e}")
        else:
            logger.info("[dev3] ❌ Немає пари з позитивним score для fallback")

    if accepted_count == 0:
        notify_all_skipped(avg)

    logger.info("[dev3] ✅ Цикл завершено")
