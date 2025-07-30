from __future__ import annotations

import json
import os
from typing import List, Dict, Any

from convert_api import get_quote, accept_quote, get_balances
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
)
from quote_counter import should_throttle, reset_cycle
from convert_model import _hash_token
from utils_dev3 import safe_float


def gpt_score(data: Dict[str, Any]) -> float:
    score = data.get("score", 0.0)
    if isinstance(score, (int, float)):
        return float(score)
    elif isinstance(score, dict):
        # Якщо score — це словник (наприклад: {"value": 0.81}), беремо значення ключа "value"
        return float(score.get("value", 0.0))
    return 0.0

MAX_QUOTES_PER_CYCLE = 20
TOP_N_PAIRS = 10
GPT_SCORE_THRESHOLD = 0.5


def try_convert(from_token: str, to_token: str, amount: float, score: float) -> bool:
    """Attempt a single conversion and log the result."""
    log_prediction(from_token, to_token, score)
    if amount <= 0:
        log_quote_skipped(from_token, to_token, "no_balance")
        return False

    if should_throttle(from_token, to_token):
        log_quote_skipped(from_token, to_token, "throttled")
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
    if resp and resp.get("success") is True:
        profit = safe_float(resp.get("toAmount", 0)) - safe_float(resp.get("fromAmount", 0))
        log_conversion_success(from_token, to_token, profit)
        notify_success(
            from_token,
            to_token,
            safe_float(resp.get("fromAmount", 0)),
            safe_float(resp.get("toAmount", 0)),
            score,
            safe_float(quote.get("ratio", 0)) - 1,
        )
        features = [
            safe_float(quote.get("ratio", 0)),
            safe_float(quote.get("inverseRatio", 0)),
            safe_float(amount),
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
    save_convert_history(
        {
            "from": from_token,
            "to": to_token,
            "features": [
                safe_float(quote.get("ratio", 0)),
                safe_float(quote.get("inverseRatio", 0)),
                safe_float(amount),
                _hash_token(from_token),
                _hash_token(to_token),
            ],
            "profit": 0.0,
            "accepted": False,
        }
    )
    return False


def fallback_convert(pairs: List[Dict[str, Any]], balances: Dict[str, float]) -> bool:
    """Attempt fallback conversion using the token with the highest balance.

    Returns True if a conversion was successfully executed.
    """

    # Choose token with the largest balance excluding stablecoins and delisted tokens
    candidates = [
        (token, amt)
        for token, amt in balances.items()
        if amt > 0 and token not in ("USDT", "AMB", "DELISTED")
    ]
    fallback_token = max(candidates, key=lambda x: x[1], default=(None, 0.0))[0]

    if not fallback_token:
        logger.warning("🔹 [FALLBACK] Не знайдено жодного токена з балансом для fallback")
        return False

    valid_to_tokens = [
        p
        for p in pairs
        if p.get("from_token") == fallback_token
        and gpt_score(p) > GPT_SCORE_THRESHOLD
    ]

    if not valid_to_tokens:
        logger.warning(f"🔹 [FALLBACK] Актив '{fallback_token}' з найбільшим балансом не сконвертовано")
        logger.warning("🔸 Причина: не знайдено жодного валідного `to_token` для fallback (score недостатній або немає прогнозу)")
        return False

    best_pair = max(valid_to_tokens, key=lambda x: gpt_score(x))
    selected_to_token = best_pair.get("to_token")
    amount = balances.get(fallback_token, 0.0)
    from convert_api import get_max_convert_amount
    max_allowed = get_max_convert_amount(fallback_token, selected_to_token)
    if amount > max_allowed:
        amount = max_allowed
    logger.info(f"🔄 [FALLBACK] Спроба конвертації {fallback_token} → {selected_to_token}")

    return try_convert(
        fallback_token,
        selected_to_token,
        amount,
        gpt_score(best_pair),
    )


def _load_top_pairs() -> List[Dict[str, Any]]:
    path = os.path.join(os.path.dirname(__file__), "top_tokens.json")
    if not os.path.exists(path):
        logger.warning("[dev3] top_tokens.json not found")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # pragma: no cover - file issues
        logger.warning("[dev3] failed to read top_tokens.json: %s", exc)
        return []

    # Normalize format: handle both [(score, quote), ...] and [{...}, ...]
    top_quotes: List[tuple[float, Dict[str, Any]]] = []
    for item in data:
        if isinstance(item, dict):
            score_val = safe_float(item.get("score"))
            if score_val is None:
                score_val = item.get("gpt", {}).get("score", 0)
            if isinstance(score_val, dict):
                score_val = score_val.get("predicted", score_val.get("value", 0))
            score = safe_float(score_val)
            top_quotes.append((score, item))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            score = safe_float(item[0])
            quote = item[1]
            if isinstance(quote, dict):
                top_quotes.append((score, quote))
        else:
            logger.debug("[dev3] invalid item in top_tokens.json: %s", item)

    top_quotes = sorted(top_quotes, key=lambda x: x[0], reverse=True)
    return [q for _, q in top_quotes]


def process_top_pairs(pairs: List[Dict[str, Any]] | None = None) -> None:
    """Process top pairs from daily analysis."""
    reset_cycle()
    logger.info("[dev3] ▶️ Запуск циклу конверсії через Binance Convert API")
    if pairs is None:
        pairs = _load_top_pairs()
    if not pairs:
        logger.warning(
            "[dev3] ⛔ Усі пари відкинуті фільтрами — цикл завершено без спроб отримати quote."
        )
        return

    top_token_pairs_raw = list(pairs)
    binance_balances = get_binance_balances()
    available_from_tokens = [
        token
        for token, amt in binance_balances.items()
        if amt > 0 and token not in ("USDT", "AMB", "DELISTED")
    ]
    pairs = [p for p in pairs if p.get("from_token") in available_from_tokens]

    balances = get_balances()
    successful_count = 0

    if not pairs:
        if binance_balances:
            if fallback_convert(top_token_pairs_raw, binance_balances):
                successful_count = 1
                logger.info(
                    f"[dev3] ✅ Успішно завершено цикл. Виконано {successful_count} конверсій."
                )
            else:
                logger.info(
                    "[dev3] ❌ Жодна з пар не пройшла accept_quote — цикл завершено без виконання."
                )
        else:
            logger.warning("[dev3] No available tokens for fallback")
        return

    pairs = [
        p
        for p in pairs
        if gpt_score(p) > GPT_SCORE_THRESHOLD
    ]
    pairs.sort(key=lambda x: gpt_score(x), reverse=True)
    quote_count = 0
    any_successful_conversion = False
    successful_count = 0
    valid_quote_count = 0
    scored_quotes: List[Dict[str, Any]] = []

    for item in pairs[:TOP_N_PAIRS]:
        if quote_count >= MAX_QUOTES_PER_CYCLE:
            log_skipped_quotes()
            break

        from_token = item.get("from_token")
        to_token = item.get("to_token")
        score = item.get("score", 0)
        if isinstance(score, dict):
            score = score.get("value", score.get("predicted", 0))

        expected_profit = item.get("expected_profit", 0)
        if isinstance(expected_profit, dict):
            expected_profit = expected_profit.get(
                "value", expected_profit.get("predicted", 0)
            )

        prob_up = item.get("prob_up", 0)
        if isinstance(prob_up, dict):
            prob_up = prob_up.get("value", prob_up.get("predicted", 0))

        logger.debug(
            f"[dev3] 🧪 Обробка: score={score}, expected_profit={expected_profit}, prob_up={prob_up}"
        )

        score = safe_float(score)
        expected_profit = safe_float(expected_profit)
        prob_up = safe_float(prob_up)
        amount = balances.get(from_token, 0)
        from convert_api import get_max_convert_amount
        max_allowed = get_max_convert_amount(from_token, to_token)
        if amount > max_allowed:
            amount = max_allowed

        log_prediction(from_token, to_token, score)

        if amount <= 0:
            log_quote_skipped(from_token, to_token, "no_balance")
            continue

        if should_throttle(from_token, to_token):
            log_quote_skipped(from_token, to_token, "throttled")
            continue

        quote = get_quote(from_token, to_token, amount)
        quote_count += 1

        if not quote or quote.get("price") is None or quote.get("code") == 401:
            log_quote_skipped(from_token, to_token, "invalid_quote")
            logger.warning(
                f"[dev3] ⚠️ quote недоступний для {from_token} → {to_token} — причина: {quote}"
            )
            continue
        valid_quote_count += 1

        valid, reason = passes_filters(score, quote, amount)
        if not valid:
            logger.info(
                f"[dev3] \u26d4\ufe0f Пропуск {from_token} → {to_token}: score={score:.4f}, причина={reason}, quote={quote}"
            )
            scored_quotes.append(
                {
                    "from_token": from_token,
                    "to_token": to_token,
                    "score": score,
                    "quote": quote.get("quoteId"),
                    "skip_reason": reason,
                }
            )
            continue

        quote_id = quote.get("quoteId")
        resp = accept_quote(quote_id) if quote_id else None
        if resp and resp.get("success") is True:
            any_successful_conversion = True
            successful_count += 1
            logger.info("[dev3] ✅ Трейд успішно прийнято Binance")
            profit = safe_float(resp.get("toAmount", 0)) - safe_float(resp.get("fromAmount", 0))
            log_conversion_success(from_token, to_token, profit)
            notify_success(
                from_token,
                to_token,
                safe_float(resp.get("fromAmount", 0)),
                safe_float(resp.get("toAmount", 0)),
                score,
                safe_float(quote.get("ratio", 0)) - 1,
            )
            features = [
                safe_float(quote.get("ratio", 0)),
                safe_float(quote.get("inverseRatio", 0)),
                safe_float(amount),
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
            save_convert_history(
                {
                    "from": from_token,
                    "to": to_token,
                    "features": [
                        safe_float(quote.get("ratio", 0)),
                        safe_float(quote.get("inverseRatio", 0)),
                        safe_float(amount),
                        _hash_token(from_token),
                        _hash_token(to_token),
                    ],
                    "profit": 0.0,
                    "accepted": False,
                }
            )

    if valid_quote_count == 0:
        logger.warning(
            "[dev3] ❌ Всі quote недоступні (price=None) — цикл завершено без угод."
        )
        return

    if not any_successful_conversion and scored_quotes:
        fallback = max(scored_quotes, key=lambda x: gpt_score(x))
        log_reason = fallback.get("skip_reason", "no reason")
        logger.info(
            f"[dev3] ⚠️ Жодна пара не пройшла фільтри. Виконуємо fallback-конверсію: {fallback['from_token']} → {fallback['to_token']} (score={fallback['score']:.2f}, причина skip: {log_reason})"
        )

        logger.info(
            f"🔄 [FALLBACK] Спроба конвертації {fallback['from_token']} → {fallback['to_token']}"
        )
        try:
            quote_id = fallback["quote"]
            resp = accept_quote(quote_id) if quote_id else None
            if resp and resp.get("success") is True:
                logger.info("[dev3] ✅ Fallback трейд успішно виконано Binance")
                profit = safe_float(resp.get("toAmount", 0)) - safe_float(resp.get("fromAmount", 0))
                log_conversion_success(fallback["from_token"], fallback["to_token"], profit)
                notify_success(
                    fallback["from_token"],
                    fallback["to_token"],
                    safe_float(resp.get("fromAmount", 0)),
                    safe_float(resp.get("toAmount", 0)),
                    safe_float(fallback.get("score")),
                    safe_float(resp.get("ratio", 0)) - 1 if "ratio" in resp else 0,
                )
                save_convert_history(
                    {
                        "from": fallback["from_token"],
                        "to": fallback["to_token"],
                        "features": [],
                        "profit": profit,
                        "accepted": True,
                    }
                )
                any_successful_conversion = True
                successful_count += 1
            else:
                reason = resp.get("msg") if isinstance(resp, dict) else "Unknown error"
                logger.warning(
                    "[dev3] ❌ Fallback трейд НЕ відбувся: %s → %s. Причина: %s",
                    fallback["from_token"],
                    fallback["to_token"],
                    reason,
                )
                log_conversion_error(fallback["from_token"], fallback["to_token"], reason)
                notify_failure(fallback["from_token"], fallback["to_token"], reason=reason)
                save_convert_history(
                    {
                        "from": fallback["from_token"],
                        "to": fallback["to_token"],
                        "features": [],
                        "profit": 0.0,
                        "accepted": False,
                    }
                )
        except Exception as e:
            logger.error(f"[dev3] ❌ Помилка під час fallback-конверсії: {e}")

    if successful_count > 0:
        logger.info(
            f"[dev3] ✅ Успішно завершено цикл. Виконано {successful_count} конверсій."
        )
    else:
        logger.info(
            "[dev3] ❌ Жодна з пар не пройшла accept_quote — цикл завершено без виконання."
        )

