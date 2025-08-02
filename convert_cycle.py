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
    log_skipped_quotes,
    log_error,
)
from quote_counter import should_throttle, reset_cycle
from convert_model import _hash_token
from utils_dev3 import safe_float


def _metric_value(val: Any) -> float:
    """Return float metric from raw value or nested dict."""
    if isinstance(val, dict):
        val = val.get("value", val.get("predicted", 0))
    return safe_float(val)


def gpt_score(data: Dict[str, Any]) -> float:
    """Return score as float using ``safe_float`` for robustness."""
    score_data = data.get("score", 0)
    if isinstance(score_data, dict):
        score = score_data.get("score", 0)
    else:
        score = score_data
    return _metric_value(score)


_balances_cache: Dict[str, float] | None = None


def get_token_balances() -> Dict[str, float]:
    """Return balances for all tokens using cached Binance data."""
    global _balances_cache
    if _balances_cache is None:
        try:
            _balances_cache = get_balances()
        except Exception as exc:  # pragma: no cover - network
            logger.warning("[dev3] ❌ get_token_balances помилка: %s", exc)
            _balances_cache = {}
    return _balances_cache

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

    resp = accept_quote(quote, from_token, to_token)
    if resp and resp.get("success") is True:
        profit = safe_float(resp.get("toAmount", 0)) - safe_float(resp.get("fromAmount", 0))
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

    best_pair = max(valid_to_tokens, key=gpt_score)
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
            score_val = item.get("score")
            if score_val is None:
                score_val = item.get("gpt", {}).get("score", 0)
            score = _metric_value(score_val)
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
    """Process top token pairs and execute conversions if score is high enough."""
    logger.info("[dev3] 🔍 Запуск process_top_pairs з %d парами", len(pairs) if pairs else 0)

    balances = get_token_balances()
    if not pairs:
        logger.warning("[dev3] ⛔️ Список пар порожній — нічого обробляти")
        return

    filtered_pairs = []
    for p in pairs:
        score = gpt_score(p)
        from_token = (
            p.get("from_token") or p.get("from") or p.get("symbol_from")
        )
        to_token = p.get("to_token") or p.get("to") or p.get("symbol_to")
        if not from_token or not to_token:
            logger.warning(
                "[dev3] ❗️ Неможливо визначити токени з пари: %s", p
            )
            continue

        if from_token not in balances:
            logger.info("[dev3] ⏭ Пропущено %s → %s: немає балансу", from_token, to_token)
            continue

        if score <= GPT_SCORE_THRESHOLD:
            logger.info(
                "[dev3] ⏭ Пропущено %s → %s: score=%.4f нижче %.2f",
                from_token,
                to_token,
                score,
                GPT_SCORE_THRESHOLD,
            )
            continue

        filtered_pairs.append(p)

    logger.info("[dev3] ✅ Кількість пар після фільтрації: %d", len(filtered_pairs))

    if not filtered_pairs:
        logger.warning("[dev3] ⛔️ Жодна пара не пройшла фільтри — трейд пропущено")
        fallback_convert(pairs, balances)
        return

    successful_count = 0
    quote_count = 0
    for p in filtered_pairs:
        if quote_count >= MAX_QUOTES_PER_CYCLE:
            logger.info(
                "[dev3] ⛔️ Досягнуто ліміту %d запитів на котирування",
                MAX_QUOTES_PER_CYCLE,
            )
            break

        from_token = (
            p.get("from_token") or p.get("from") or p.get("symbol_from")
        )
        to_token = p.get("to_token") or p.get("to") or p.get("symbol_to")
        if not from_token or not to_token:
            logger.warning(
                "[dev3] ❗️ Неможливо визначити токени з пари: %s", p
            )
            continue
        amount = balances.get(from_token, 0)
        score = gpt_score(p)

        if amount <= 0:
            logger.info(
                "[dev3] ⏭ %s → %s: amount %.4f недостатній",
                from_token,
                to_token,
                amount,
            )
            continue

        if try_convert(from_token, to_token, amount, score):
            successful_count += 1
            quote_count += 1

    logger.info("[dev3] ✅ Успішних конверсій: %d", successful_count)

    if successful_count == 0:
        logger.warning("[dev3] ⚠️ Жодної конверсії не виконано — викликаємо fallback")
        fallback_convert(pairs, balances)
