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
    save_convert_history(
        {
            "from": from_token,
            "to": to_token,
            "features": [
                float(quote.get("ratio", 0)),
                float(quote.get("inverseRatio", 0)),
                float(amount),
                _hash_token(from_token),
                _hash_token(to_token),
            ],
            "profit": 0.0,
            "accepted": False,
        }
    )
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
        logger.warning("🔹 [FALLBACK] Не знайдено жодного токена з балансом для fallback")
        return

    valid_to_tokens = [p for p in pairs if p.get("from_token") == fallback_token]

    if not valid_to_tokens:
        logger.warning(f"🔹 [FALLBACK] Актив '{fallback_token}' з найбільшим балансом не сконвертовано")
        logger.warning("🔸 Причина: не знайдено жодного валідного `to_token` для fallback (score недостатній або немає прогнозу)")
        return

    best_pair = max(valid_to_tokens, key=lambda x: x.get("score", 0))
    selected_to_token = best_pair.get("to_token")
    amount = balances.get(fallback_token, 0.0)
    logger.info(f"🔄 [FALLBACK] Спроба конвертації {fallback_token} → {selected_to_token}")

    try_convert(
        fallback_token,
        selected_to_token,
        amount,
        float(best_pair.get("score", 0)),
    )


def _load_top_pairs() -> List[Dict[str, Any]]:
    path = os.path.join(os.path.dirname(__file__), "top_tokens.json")
    if not os.path.exists(path):
        logger.warning("[dev3] top_tokens.json not found")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
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

    balances = get_balances()

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
            save_convert_history(
                {
                    "from": from_token,
                    "to": to_token,
                    "features": [
                        float(quote.get("ratio", 0)),
                        float(quote.get("inverseRatio", 0)),
                        float(amount),
                        _hash_token(from_token),
                        _hash_token(to_token),
                    ],
                    "profit": 0.0,
                    "accepted": False,
                }
            )

    if not any_successful_conversion and scored_quotes:
        fallback = max(scored_quotes, key=lambda x: x["score"])
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
                profit = float(resp.get("toAmount", 0)) - float(resp.get("fromAmount", 0))
                log_conversion_success(fallback["from_token"], fallback["to_token"], profit)
                notify_success(
                    fallback["from_token"],
                    fallback["to_token"],
                    float(resp.get("fromAmount", 0)),
                    float(resp.get("toAmount", 0)),
                    fallback["score"],
                    float(resp.get("ratio", 0)) - 1 if "ratio" in resp else 0,
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

    logger.info("[dev3] ✅ Цикл завершено")

