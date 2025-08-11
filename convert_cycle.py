from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from convert_api import (
    get_quote,
    accept_quote,
    get_balances,
    get_order_status,
    ORDER_POLL_MAX_SEC,
    ORDER_POLL_INTERVAL,
)
from binance_api import get_binance_balances, get_ratio
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
from utils_dev3 import (
    safe_float,
    safe_json_load,
    safe_json_dump,
    HISTORY_PATH,
)

EXPLORE_MODE = int(os.getenv("EXPLORE_MODE", "0"))
EXPLORE_MIN_EDGE = safe_float(os.environ.get("EXPLORE_MIN_EDGE", "0.001"))


def _pick_best_by_edge(candidates: list[dict[str, Any]]):
    best = None
    best_edge = -1.0
    for c in candidates:
        from_token = c.get("from")
        to_token = c.get("to")
        quote = c.get("quote", {})
        spot_ratio = get_ratio(from_token, to_token)
        spot_inv = 1 / spot_ratio if spot_ratio else 0
        quote_inv = safe_float(quote.get("inverseRatio", 0))
        edge = (spot_inv - quote_inv) / spot_inv if spot_inv > 0 else -1.0
        c["edge"] = edge
        if edge > best_edge:
            best_edge = edge
            best = c
    return best, best_edge


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


# Єдине місце читання/запису історії
history_file = HISTORY_PATH


def load_history() -> list[dict]:
    data = safe_json_load(history_file, default=[])
    if not isinstance(data, list):
        return []
    return data


def save_history(items: list[dict]) -> None:
    try:
        safe_json_dump(history_file, items)
    except Exception as e:  # pragma: no cover - filesystem
        logger.error("❌ Помилка при збереженні історії: %s", e)


def _score_of(item: dict) -> float:
    # нормалізація: шукаємо score на різних рівнях
    for key_path in (("score",), ("gpt", "score"), ("model", "score")):
        cur = item
        try:
            for k in key_path:
                cur = cur[k]
            return float(cur)
        except Exception:
            continue
    return 0.0


def select_top_pairs(pairs: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    # фільтр від None токенів ДО сортування
    norm: List[Dict[str, Any]] = []
    for p in pairs or []:
        ft = p.get("from") or p.get("from_token") or p.get("fromToken")
        tt = p.get("to") or p.get("to_token") or p.get("toToken")
        if not (isinstance(ft, str) and isinstance(tt, str) and ft and tt):
            logger.warning("❌ Один із токенів None: from_token=%s, to_token=%s", ft, tt)
            continue
        norm.append(p)
    pairs_sorted = sorted(norm, key=_score_of, reverse=True)
    return pairs_sorted[:limit]


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
    if isinstance(resp, dict):
        order_id = str(resp.get("orderId", ""))
        status = str(resp.get("orderStatus", resp.get("status", "")))
        if status == "PROCESS" and order_id:
            start = time.time()
            while time.time() - start < ORDER_POLL_MAX_SEC:
                st = get_order_status(order_id)
                if not st:
                    time.sleep(ORDER_POLL_INTERVAL)
                    continue
                st_code = str(st.get("orderStatus", ""))
                if st_code in ("SUCCESS", "FAILED", "FAIL", "EXPIRED", "CANCELED"):
                    resp = st
                    status = st_code
                    resp["status"] = "success" if st_code == "SUCCESS" else "error"
                    break
                time.sleep(ORDER_POLL_INTERVAL)
            logger.info(
                "[dev3] ✅ orderId=%s final status=%s", order_id, status or "UNKNOWN"
            )
        if resp.get("status") != "success":
            logger.warning(
                "❌ Конверсія не підтверджена: orderId=%s status=%s",
                order_id,
                status,
            )
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

    # ENV-прапори explore режиму
    EXPLORE_MODE = os.getenv("EXPLORE_MODE", "1") == "1"
    EXPLORE_MAX = int(os.getenv("EXPLORE_MAX", "2"))
    EXPLORE_PAPER = os.getenv("EXPLORE_PAPER", "1") == "1"
    EXPLORE_MIN_LOT_FACTOR = safe_float(os.getenv("EXPLORE_MIN_LOT_FACTOR", "1.0")) or 1.0

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
    all_quotes: List[tuple[str, str, float, Dict[str, Any], float]] = []
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
            all_quotes.append((from_token, to_token, amount, quote, score))
            continue

        valid, reason = passes_filters(score, quote, amount)
        if not valid:
            logger.info(
                safe_log(
                    f"[dev3] ⛔️ Пропуск {from_token} → {to_token}: score={score:.4f}, причина={reason}, quote={quote}"
                )
            )
            if reason == "spot_no_profit" and score > 0:
                fallback_candidates.append((from_token, to_token, amount, quote, score))
                logger.info(
                    safe_log(
                        f"[dev3] ⚠ Навчальна пара: {from_token} → {to_token} (score={score:.4f})"
                    )
                )
                continue
            all_quotes.append((from_token, to_token, amount, quote, score))
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

    if successful_count == 0 and EXPLORE_MODE:
        all_checked_candidates = [
            {"from": f, "to": t, "amount": amt, "quote": q}
            for f, t, amt, q, sc in all_quotes
        ]
        best, best_edge = _pick_best_by_edge(all_checked_candidates)
        if best and best_edge >= EXPLORE_MIN_EDGE:
            logger.info(
                safe_log(
                    f"[FALLBACK-EXPLORE] Виконуємо паперову угоду {best['from']}→{best['to']} edge={best_edge:.4%}"
                )
            )
            try:
                explore_amt = best.get("amount", 0)
                q = best.get("quote", {})
                if EXPLORE_PAPER:
                    faux_profit = safe_float(q.get("toAmount", 0)) - safe_float(q.get("fromAmount", 0))
                    logger.info(
                        safe_log(
                            f"[dev3] [PAPER] ✅ Explore fallback {best['from']}→{best['to']} profit={faux_profit:.8f}"
                        )
                    )
                    save_convert_history(
                        {
                            "from": best["from"],
                            "to": best["to"],
                            "features": [
                                safe_float(q.get("ratio", 0)),
                                safe_float(q.get("inverseRatio", 0)),
                                safe_float(explore_amt),
                                _hash_token(best["from"]),
                                _hash_token(best["to"]),
                            ],
                            "profit": faux_profit,
                            "accepted": False,
                            "paper": True,
                        }
                    )
                    successful_count += 1
                else:
                    logger.warning(
                        safe_log(
                            f"[dev3] 🧭 Explore EXEC {best['from']}→{best['to']} amount={explore_amt:.8f}"
                        )
                    )
                    if try_convert(best["from"], best["to"], explore_amt, 0.01, q):
                        successful_count += 1
            except Exception as e:
                logger.warning(safe_log(f"Fallback-explore помилка: {e}"))
        else:
            logger.info(
                safe_log(
                    "[FALLBACK-EXPLORE] Немає кандидатів з позитивним edge ≥ EXPLORE_MIN_EDGE"
                )
            )

    if successful_count == 0:
        logger.warning(safe_log("[dev3] ⚠️ Жодної конверсії не виконано — викликаємо fallback"))
        fallback_convert(pairs, balances)
