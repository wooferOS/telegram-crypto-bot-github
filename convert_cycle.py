from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from convert_api import (
    get_balances,
    get_order_status,
    ORDER_POLL_MAX_SEC,
    ORDER_POLL_INTERVAL,
    accept_quote_old,
)
from binance_api import get_quote
from run_convert_trade import load_top_pairs
from convert_filters import (
    passes_filters,
    get_token_info,
    _compute_edge,
    find_wallet_with_quote_id,
)
from convert_logger import (
    logger,
    save_convert_history,
    log_prediction,
    log_quote_skipped,
    log_skipped_quotes,
    log_error,
    safe_log,
    err_logger,
    trade_logger,
)
from convert_api import accept_quote as accept_quote_raw, _sync_time
from binance_api import get_binance_balances, get_ratio
from convert_notifier import notify_success, notify_failure
from quote_counter import should_throttle, reset_cycle
from convert_model import _hash_token, predict, model_is_valid
from utils_dev3 import safe_float, safe_json_load, safe_json_dump, HISTORY_PATH

# Зворотна сумісність для старих функцій
accept_quote = accept_quote_old

FIAT_TOKENS = {"COP", "RON", "MXN"}


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
        edge = _compute_edge(spot_inv, quote_inv)
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


def _write_summary(
    stats: Dict[str, int],
    best_edge: float,
    candidates: int,
    fallback_attempted: bool,
    fallback_result: bool,
) -> None:
    summary = {
        **stats,
        "best_edge": best_edge,
        "candidates": candidates,
        "fallback_attempted": fallback_attempted,
        "fallback_result": fallback_result,
    }
    os.makedirs("logs", exist_ok=True)
    with open("logs/convert_summary.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")


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
) -> Tuple[bool, str]:
    """Attempt a single conversion using optional pre-fetched quote."""
    log_prediction(from_token, to_token, score)
    if amount <= 0:
        log_quote_skipped(from_token, to_token, "no_balance")
        return False, "other"

    if should_throttle(from_token, to_token):
        log_quote_skipped(from_token, to_token, "throttled")
        return False, "other"

    quote = quote_data or get_quote(
        from_asset=from_token, to_asset=to_token, amount_from=amount
    )
    if not quote:
        log_quote_skipped(from_token, to_token, "invalid_quote")
        return False, "no_quote"

    resp = accept_quote(quote, from_token, to_token)
    if resp is None:
        notify_failure(from_token, to_token, reason="accept_quote returned None")
        return False, "api_error"
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
        return True, "ok"

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
    return False, "api_error"


def fallback_convert(
    pairs: List[Dict[str, Any]],
    balances: Dict[str, float],
    config: Dict[str, Any],
    stats: Dict[str, int],
) -> bool:
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

    quote = get_quote(
        from_asset=from_token, to_asset=selected_to_token, amount_from=amount
    )
    if not quote:
        stats["no_quote"] += 1
        return False
    valid, reason, _ = passes_filters(
        gpt_score(best_pair),
        quote,
        amount,
        context="fallback",
        explore_min_edge=config.get("min_edge", 0.0),
        min_lot_factor=config.get("min_lot_factor", 1.0),
    )
    if not valid:
        if reason == "price_zero":
            stats["price_zero"] += 1
        elif reason == "min_lot":
            stats["min_lot"] += 1
        else:
            stats["other"] += 1
        return False
    success, fail_reason = try_convert(
        from_token,
        selected_to_token,
        amount,
        gpt_score(best_pair),
        quote,
    )
    if success:
        stats["accepted_quotes"] += 1
        return True
    if fail_reason == "api_error":
        stats["api_error"] += 1
    else:
        stats["other"] += 1
    return False




def process_top_pairs_old(
    pairs: List[Dict[str, Any]] | None = None,
    config: Dict[str, Any] | None = None,
) -> None:
    config = config or {}
    logger.info(
        safe_log(
            f"[dev3] 🔍 Запуск process_top_pairs з {len(pairs) if pairs else 0} парами"
        )
    )

    balances = get_token_balances()
    if not pairs:
        logger.warning(safe_log("[dev3] ⛔️ Список пар порожній — нічого обробляти"))
        return

    non_tradable = 0
    tradable: List[Dict[str, Any]] = []
    for p in pairs:
        ft = p.get("fromToken") or p.get("from")
        tt = p.get("toToken") or p.get("to")
        if not ft or not tt or ft == tt or ft in FIAT_TOKENS or tt in FIAT_TOKENS:
            non_tradable += 1
            continue
        tradable.append(p)
    if non_tradable:
        logger.info(safe_log(f"[dev3] ℹ️ Відсіяно {non_tradable} non-tradable пар"))
    non_zero_pairs: List[Dict[str, Any]] = []
    for p in tradable:
        sc = float(p.get("score", 0) or 0)
        ep = float(p.get("expected_profit", 0) or 0)
        pu = float(p.get("prob_up", 0) or 0)
        if sc == 0.0 and ep == 0.0 and pu == 0.0:
            continue
        non_zero_pairs.append(p)
    if not non_zero_pairs:
        logger.info(
            safe_log(
                "[dev3] ℹ️ Усі пари мають нульовий score — цикл завершено без запитів"
            )
        )
        return

    filtered_pairs: List[Dict[str, Any]] = []
    for pair in non_zero_pairs:
        score = gpt_score(pair)
        from_key = pair.get("fromToken") or pair.get("from_token") or pair.get("from")
        to_key = pair.get("toToken") or pair.get("to_token") or pair.get("to")
        from_info = get_token_info(from_key)
        to_info = get_token_info(to_key)
        from_token = from_info.get("symbol") if from_info else None
        to_token = to_info.get("symbol") if to_info else None
        if not from_token or not to_token:
            continue
        if from_token not in balances:
            continue
        filtered_pairs.append(pair)

    logger.info(
        safe_log(f"[dev3] ✅ Кількість пар після фільтрації: {len(filtered_pairs)}")
    )

    stats = {
        "predict_skip_negative": 0,
        "edge_too_small_explore": 0,
        "price_zero": 0,
        "min_lot": 0,
        "no_quote": 0,
        "api_error": 0,
        "other": 0,
        "accepted_quotes": 0,
    }
    best_edge = -1.0
    fallback_attempted = False
    fallback_result = False

    if not filtered_pairs:
        logger.warning(
            safe_log("[dev3] ⛔️ Жодна пара не пройшла фільтри — трейд пропущено")
        )
        fallback_attempted = True
        fallback_result = fallback_convert(tradable, balances, config, stats)
        _write_summary(stats, best_edge, len(filtered_pairs), fallback_attempted, fallback_result)
        return

    successful_count = 0
    quote_count = 0
    all_checked: List[dict] = []
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
            stats["other"] += 1
            continue

        amount = balances.get(from_token, 0)
        if amount <= 0:
            stats["other"] += 1
            continue

        if should_throttle(from_token, to_token):
            stats["other"] += 1
            continue

        quote = pair.get("quote") or get_quote(
            from_asset=from_token, to_asset=to_token, amount_from=amount
        )
        if not quote:
            log_quote_skipped(from_token, to_token, "invalid_quote")
            stats["no_quote"] += 1
            continue
        quote_count += 1

        expected_profit, prob_up, score = predict(from_token, to_token, quote)
        logger.info(
            safe_log(
                f"[dev3] \U0001f4ca Модель: {from_token} → {to_token}: profit={expected_profit:.4f}, prob={prob_up:.4f}, score={score:.4f}"
            )
        )

        if score <= 0 and model_is_valid() and not config.get("model_only", False):
            stats["predict_skip_negative"] += 1
            all_checked.append({"from": from_token, "to": to_token, "amount": amount, "quote": quote})
            continue

        valid, reason, edge = passes_filters(
            score,
            quote,
            amount,
            context="explore",
            explore_min_edge=config.get("min_edge", 0.0),
            min_lot_factor=config.get("min_lot_factor", 1.0),
        )
        best_edge = max(best_edge, edge)
        if not valid:
            if reason == "edge_too_small_explore":
                stats["edge_too_small_explore"] += 1
            elif reason == "price_zero":
                stats["price_zero"] += 1
            elif reason == "min_lot":
                stats["min_lot"] += 1
            else:
                stats["other"] += 1
            all_checked.append({"from": from_token, "to": to_token, "amount": amount, "quote": quote})
            continue

        success, fail_reason = try_convert(from_token, to_token, amount, score, quote)
        if success:
            stats["accepted_quotes"] += 1
            successful_count += 1
            quote_count += 1
        else:
            if fail_reason == "api_error":
                stats["api_error"] += 1
            else:
                stats["other"] += 1
        all_checked.append({"from": from_token, "to": to_token, "amount": amount, "quote": quote})

    logger.info(safe_log(f"[dev3] ✅ Успішних конверсій: {successful_count}"))

    if successful_count == 0 and config.get("mode"):
        best, edge_val = _pick_best_by_edge(all_checked)
        best_edge = max(best_edge, edge_val)
        if best and edge_val >= config.get("min_edge", 0.0):
            try:
                explore_amt = best.get("amount", 0)
                q = best.get("quote", {})
                if config.get("paper", True):
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
                    if try_convert(best["from"], best["to"], explore_amt, 0.01, q)[0]:
                        successful_count += 1
            except Exception as e:
                logger.warning(safe_log(f"Fallback-explore помилка: {e}"))

    if successful_count == 0:
        logger.warning(
            safe_log("[dev3] ⚠️ Жодної конверсії не виконано — викликаємо fallback")
        )
        fallback_attempted = True
        fallback_result = fallback_convert(tradable, balances, config, stats)

    _write_summary(
        stats,
        best_edge,
        len(filtered_pairs),
        fallback_attempted,
        fallback_result,
    )


def process_top_pairs(pairs: List[Dict[str, Any]] | None = None, config: Dict[str, Any] | None = None) -> None:
    """Спрощений цикл конвертації на базі нових обгорток."""
    config = config or {}
    if pairs is None:
        pairs = load_top_pairs("top_tokens.json")
    logger.info(
        "[dev3] 🔍 Запуск process_top_pairs з %d парами", len(pairs) if pairs else 0
    )
    _sync_time()

    for pair in pairs or []:
        amount_quote = float(pair["amount_quote"])
        from_sym = pair["from"]
        to_sym = pair["to"]
        wallet = pair.get("wallet", "SPOT")
        logger.info(
            "🔎 getQuote try: %s→%s wallet=%s amount=%.6f",
            from_sym,
            to_sym,
            wallet,
            amount_quote,
        )
        quote = pair.get("quote") or get_quote(
            from_asset=from_sym,
            to_asset=to_sym,
            amount_quote=amount_quote,
            wallet=wallet,
        )
        if not quote:
            logger.info("⏭️  convert skipped (no_quote): %s", pair)
            continue
        wtype = wallet
        acc = accept_quote_raw(quote.get("quoteId")) if quote else None
        if acc and acc.get("status") == 200:
            trade_logger.info(
                "[dev3] ✅ Конверсія %s→%s amount=%s wallet=%s result=%s",
                from_sym,
                to_sym,
                amount_quote,
                wtype,
                acc.get("json") if isinstance(acc, dict) else acc,
            )
        else:
            err_logger.error(
                "[dev3] ❌ acceptQuote failed: %s→%s wallet=%s resp=%s",
                from_sym,
                to_sym,
                wtype,
                acc,
            )

