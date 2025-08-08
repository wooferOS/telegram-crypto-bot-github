from __future__ import annotations

import json
import os
from typing import List, Dict, Any

from convert_api import get_quote, accept_quote, get_balances
from binance_api import get_binance_balances
from convert_notifier import notify_success, notify_failure
from convert_filters import passes_filters, get_token_info
from convert_logger import (
    logger,
    save_convert_history,
    log_prediction,
    log_quote_skipped,
    log_skipped_quotes,
    log_error,
    safe_log,
)
from quote_counter import should_throttle, reset_cycle
from convert_model import _hash_token, predict
from utils_dev3 import safe_float


def _metric_value(val: Any) -> float:
    """Return float metric from raw value or nested dict."""
    if isinstance(val, dict):
        val = val.get("value", val.get("predicted", 0))
    return safe_float(val)


def gpt_score(data: Dict[str, Any]) -> float:
    """Prefer GPT forecast (data['gpt']['score']) and fallback to raw 'score'."""
    if not isinstance(data, dict):
        return 0.0
    g = data.get("gpt")
    if isinstance(g, dict) and g.get("score") is not None:
        return _metric_value(g.get("score"))
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
            logger.warning(safe_log(f"[dev3] ❌ get_token_balances помилка: {exc}"))
            _balances_cache = {}
    return _balances_cache

MAX_QUOTES_PER_CYCLE = 20
TOP_N_PAIRS = 10
GPT_SCORE_THRESHOLD = 0.0  # не зрізаємо все до котирувань


def try_convert(
    from_token: str,
    to_token: str,
    amount: float,
    score: float,
    quote_data: Dict[str, Any] | None = None,
) -> bool:
    """Attempt a single conversion using optional pre-fetched quote."""
    log_prediction(from_token, to_token, score)
    if amount <= 0:
        log_quote_skipped(from_token, to_token, "no_balance")
        return False

    if should_throttle(from_token, to_token):
        log_quote_skipped(from_token, to_token, "throttled")
        return False

    quote = quote_data or get_quote(from_token, to_token, amount)
    if not quote:
        log_quote_skipped(from_token, to_token, "invalid_quote")
        return False

    valid, reason = passes_filters(score, quote, amount)
    if not valid:
        logger.info(
            safe_log(
                f"[dev3] \u26d4\ufe0f Пропуск {from_token} → {to_token}: score={score:.4f}, причина={reason}, quote={quote}"
            )
        )
        return False

    resp = accept_quote(quote, from_token, to_token)
    if resp is None:
        notify_failure(from_token, to_token, reason="accept_quote returned None")
        return False
    if resp.get("status") == "success":
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
        logger.warning(safe_log("🔹 [FALLBACK] Не знайдено жодного токена з балансом для fallback"))
        return False

    valid_to_tokens = []
    for p in pairs:
        from_key = p.get("fromToken") or p.get("from_token") or p.get("from")
        to_key = p.get("toToken") or p.get("to_token") or p.get("to")

        from_info = get_token_info(from_key)
        to_info = get_token_info(to_key)
        from_token = from_info.get("symbol") if from_info else None
        to_token = to_info.get("symbol") if to_info else None

        if (
            from_token == fallback_token
            and to_token is not None
            and gpt_score(p) >= 0.0  # allow слабко-позитивні кандидати до котирування
        ):
            valid_to_tokens.append(p)

    if not valid_to_tokens:
        logger.warning(safe_log(f"🔹 [FALLBACK] Актив '{fallback_token}' з найбільшим балансом не сконвертовано"))
        logger.warning(safe_log("🔸 Причина: немає валідних `to_token` для fallback до котирувань; переходимо до звичайного завершення"))
        return False

    best_pair = max(valid_to_tokens, key=gpt_score)
    from_key = best_pair.get("fromToken") or best_pair.get("from_token") or best_pair.get("from")
    to_key = best_pair.get("toToken") or best_pair.get("to_token") or best_pair.get("to")

    from_info = get_token_info(from_key)
    to_info = get_token_info(to_key)
    from_token = from_info.get("symbol") if from_info else None
    selected_to_token = to_info.get("symbol") if to_info else None

    amount = balances.get(from_token, 0.0)
    from convert_api import get_max_convert_amount
    max_allowed = get_max_convert_amount(from_token, selected_to_token)
    if amount > max_allowed:
        amount = max_allowed
    logger.info(
        safe_log(f"🔄 [FALLBACK] Спроба конвертації {from_token} → {selected_to_token}")
    )

    return try_convert(
        from_token,
        selected_to_token,
        amount,
        gpt_score(best_pair),
    )


def _load_top_pairs() -> List[Dict[str, Any]]:
    path = os.path.join(os.path.dirname(__file__), "top_tokens.json")
    if not os.path.exists(path):
        logger.warning(safe_log("[dev3] top_tokens.json not found"))
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # pragma: no cover - file issues
        logger.warning(safe_log(f"[dev3] failed to read top_tokens.json: {exc}"))
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
            logger.debug(safe_log(f"[dev3] invalid item in top_tokens.json: {item}"))

    top_quotes = sorted(top_quotes, key=lambda x: x[0], reverse=True)
    return [q for _, q in top_quotes]


def process_top_pairs(pairs: List[Dict[str, Any]] | None = None) -> None:
    """Process top token pairs and execute conversions if score is high enough."""
    logger.info(safe_log(f"[dev3] 🔍 Запуск process_top_pairs з {len(pairs) if pairs else 0} парами"))

    balances = get_token_balances()
    if not pairs:
        logger.warning(safe_log("[dev3] ⛔️ Список пар порожній — нічого обробляти"))
        return

    filtered_pairs = []
    for pair in pairs:
        score = gpt_score(pair)
        from_key = pair.get("fromToken") or pair.get("from_token") or pair.get("from")
        to_key = pair.get("toToken") or pair.get("to_token") or pair.get("to")

        from_info = get_token_info(from_key)
        to_info = get_token_info(to_key)
        from_token = from_info.get("symbol") if from_info else None
        to_token = to_info.get("symbol") if to_info else None

        if not from_token or not to_token:
            logger.warning(safe_log(f"[dev3] ❗️ Неможливо визначити токени з пари: {pair}"))
            continue

        if from_token not in balances:
            logger.info(
                safe_log(f"[dev3] ⏭ Пропущено {from_token} → {to_token}: немає балансу")
            )
            continue

        # До котирувань НЕ зрізаємо пари високим порогом — офільтруємо після котирування в passes_filters
        if score is None:
            score = 0.0

        filtered_pairs.append(pair)

    logger.info(safe_log(f"[dev3] ✅ Кількість пар після фільтрації: {len(filtered_pairs)}"))

    if not filtered_pairs:
        logger.warning(safe_log("[dev3] ⛔️ Жодна пара не пройшла фільтри — трейд пропущено"))
        fallback_convert(pairs, balances)
        return

    successful_count = 0
    quote_count = 0
    fallback_candidates = []
    for pair in filtered_pairs:
        if quote_count >= MAX_QUOTES_PER_CYCLE:
            logger.info(
                safe_log(
                    f"[dev3] ⛔️ Досягнуто ліміту {MAX_QUOTES_PER_CYCLE} запитів на котирування"
                )
            )
            break

        from_key = pair.get("fromToken") or pair.get("from_token") or pair.get("from")
        to_key = pair.get("toToken") or pair.get("to_token") or pair.get("to")

        from_info = get_token_info(from_key)
        to_info = get_token_info(to_key)
        from_token = from_info.get("symbol") if from_info else None
        to_token = to_info.get("symbol") if to_info else None

        if not from_token or not to_token:
            logger.warning(
                safe_log(
                    f"[dev3] ❌ Один із токенів None: from_token={from_token}, to_token={to_token}"
                )
            )
            logger.info(
                safe_log(
                    f"[dev3] ⛔️ Пропуск {from_token} → {to_token}: причина=invalid_tokens"
                )
            )
            continue

        amount = balances.get(from_token, 0)
        if amount <= 0:
            logger.info(
                safe_log(
                    f"[dev3] ⏭ {from_token} → {to_token}: amount {amount:.4f} недостатній"
                )
            )
            continue

        if should_throttle(from_token, to_token):
            log_quote_skipped(from_token, to_token, "throttled")
            continue

        quote = pair.get("quote")
        if not quote:
            quote = get_quote(from_token, to_token, amount)
        if not quote:
            log_quote_skipped(from_token, to_token, "invalid_quote")
            continue

        # відтепер саме тут, після реального quote, працює модель та фільтри
        expected_profit, prob_up, score = predict(from_token, to_token, quote)
        logger.info(
            safe_log(
                f"[dev3] \U0001f4ca Модель: {from_token} → {to_token}: profit={expected_profit:.4f}, prob={prob_up:.4f}, score={score:.4f}"
            )
        )

        if score <= 0:
            logger.info(
                safe_log(
                    f"[dev3] 🔕 Пропуск після predict: score={score:.4f} для {from_token} → {to_token}"
                )
            )
            continue

        valid, reason = passes_filters(score, quote, amount)
        if not valid:
            if reason == "spot_no_profit" and score > 0:
                fallback_candidates.append((from_token, to_token, amount, quote, score))
                logger.info(
                    safe_log(
                        f"[dev3] ⚠ Навчальна пара: {from_token} → {to_token} (score={score:.4f})"
                    )
                )
                continue
            logger.info(
                safe_log(
                    f"[dev3] ⛔️ Пропуск {from_token} → {to_token}: причина={reason}, quote={quote}"
                )
            )
            continue

        if try_convert(from_token, to_token, amount, score, quote):
            successful_count += 1
            quote_count += 1

    logger.info(safe_log(f"[dev3] ✅ Успішних конверсій: {successful_count}"))

    if successful_count == 0 and fallback_candidates:
        fallback = max(fallback_candidates, key=lambda x: x[4])
        f_token, t_token, amt, quote, sc = fallback
        logger.warning(
            safe_log(
                f"[dev3] 🧪 Виконуємо навчальну конверсію: {f_token} → {t_token} (score={sc:.4f})"
            )
        )
        result = try_convert(f_token, t_token, amt, max(sc, 2.0), quote)
        if result:
            logger.info(safe_log("[dev3] ✅ Навчальна конверсія виконана"))
            successful_count += 1

    if successful_count == 0:
        logger.warning(safe_log("[dev3] ⚠️ Жодної конверсії не виконано — викликаємо fallback"))
        fallback_convert(pairs, balances)
