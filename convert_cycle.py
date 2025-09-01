from typing import List, Dict, Tuple

from convert_api import get_quote, accept_quote
from convert_logger import (
    logger,
    save_convert_history,
)
from convert_filters import filter_top_tokens
from convert_notifier import send_telegram
from quote_counter import can_request_quote, should_throttle, reset_cycle


# Allow executing quotes with low score for model training
allow_learning_quotes = True



def process_pair(from_token: str, to_tokens: List[str], amount: float, score_threshold: float) -> bool:
    logger.info(f"[dev3] 🔍 Аналіз для {from_token} → {len(to_tokens)} токенів")
    quotes_map: Dict[str, Dict] = {}
    scores: Dict[str, float] = {}
    all_tokens: Dict[str, Dict] = {}
    skipped_pairs: List[Tuple[str, float, str]] = []  # (token, score, reason)

    reset_cycle()

    for to_token in to_tokens:
        if should_throttle(from_token, to_token):
            skipped_pairs.append((to_token, 0.0, "throttled"))
            break

        quote = get_quote(from_token, to_token, amount)

        if should_throttle(from_token, to_token, quote):
            break

        if not quote or "ratio" not in quote or "quoteId" not in quote:
            logger.warning(
                f"[dev3] ❌ Не вдалося отримати коректний quote для {from_token} → {to_token}"
            )
            skipped_pairs.append((to_token, 0.0, "ratio_unavailable"))
            continue

        score = float(quote.get("score", 0))
        quotes_map[to_token] = quote
        scores[to_token] = score
        all_tokens[to_token] = {"score": score, "quote": quote}
        if score < score_threshold:
            skipped_pairs.append((to_token, score, f"low_score {score:.4f}"))

    filtered_pairs = filter_top_tokens(all_tokens, score_threshold, top_n=2)
    top_results = [(t, data["score"], data["quote"]) for t, data in filtered_pairs]

    training_candidate = None

    if top_results:
        logger.info("[dev3] ✅ Обрано токени для купівлі: %s", [t for t, _, _ in top_results])
    else:
        logger.warning("[dev3] ⚠️ Жоден токен не пройшов фільтри — виконуємо навчальну угоду.")
        # choose best available pair for training
        for token, data in sorted(all_tokens.items(), key=lambda x: x[1]["score"], reverse=True):
            quote = quotes_map.get(token)
            if quote:
                training_candidate = (token, scores.get(token, 0.0), quote)
                break
        if not training_candidate:
            logger.warning("[dev3] ❌ Немає доступної пари навіть для навчальної угоди.")
            return False

    if allow_learning_quotes and not training_candidate:
        # process one additional low-score pair for training
        for token, sc in sorted(scores.items(), key=lambda x: x[1]):
            if token not in {t for t, _, _ in top_results}:
                quote = quotes_map.get(token)
                if quote:
                    training_candidate = (token, sc, quote)
                    break

    selected_tokens = {t for t, _, _ in top_results}
    any_accepted = False

    def log_record(token: str, quote: Dict, accepted: bool, order_id: str | None, error: Dict | None) -> None:
        record = {
            "quoteId": quote.get("quoteId"),
            "orderId": order_id,
            "from_token": from_token,
            "to_token": token,
            "ratio": float(quote.get("ratio")) if quote.get("ratio") is not None else None,
            "inverseRatio": float(quote.get("inverseRatio")) if quote.get("inverseRatio") is not None else None,
            "from_amount": float(quote.get("fromAmount", 0)),
            "to_amount": float(quote.get("toAmount", 0)),
            "score": float(quote.get("score", 0)),
            "expected_profit": float(quote.get("expected_profit", quote.get("ratio", 1) - 1)),
            "prob_up": float(quote.get("prob_up", 0.5)),
            "accepted": accepted,
            "error_code": error.get("code") if error else None,
            "error_msg": error.get("msg") if error else None,
        }
        save_convert_history(record)

    for to_token, score, quote in top_results:
        accept_result = None
        try:
            accept_result = accept_quote(quote["quoteId"])
        except Exception as error:  # pragma: no cover - network/IO
            logger.warning(
                f"[dev3] ❌ Помилка під час accept_quote: {quote['quoteId']} — {error}"
            )
            accept_result = {"code": None, "msg": str(error)}

        order_id = accept_result.get("orderId") if isinstance(accept_result, dict) else None
        accepted = bool(order_id)
        if not accepted and isinstance(accept_result, dict):
            logger.warning(
                f"[dev3] ❌ Помилка під час accept_quote: {quote['quoteId']} — {accept_result}"
            )
        else:
            logger.info(f"[dev3] ✅ accept_quote успішний: {quote['quoteId']}")

        logger.info(
            f"[dev3] {'✅' if accepted else '❌'} Конверсія {from_token} → {to_token} (score={score:.4f})"
        )

        log_record(to_token, quote, accepted, order_id, accept_result if not accepted else None)
        if accepted:
            any_accepted = True

    if training_candidate:
        to_token, score, quote = training_candidate
        selected_tokens.add(to_token)
        accept_result = None
        try:
            accept_result = accept_quote(quote["quoteId"])
        except Exception as error:  # pragma: no cover - network/IO
            logger.warning(
                f"[dev3] 📊 Навчальна угода помилка: {quote['quoteId']} — {error}"
            )
            accept_result = {"code": None, "msg": str(error)}

        order_id = accept_result.get("orderId") if isinstance(accept_result, dict) else None
        accepted = bool(order_id)
        if accepted:
            logger.info(f"[dev3] 📊 Навчальна угода успішна: {quote['quoteId']}")
        else:
            logger.warning(
                f"[dev3] 📊 Навчальна угода помилка: {quote['quoteId']} — {accept_result}"
            )
        logger.info(
            f"[dev3] {'✅' if accepted else '❌'} 📊 Навчальна угода {from_token} → {to_token} (score={score:.4f})"
        )
        log_record(to_token, quote, accepted, order_id, accept_result if not accepted else None)
        if accepted:
            any_accepted = True

    for to_token in to_tokens:
        if to_token in selected_tokens:
            continue
        quote = quotes_map.get(to_token)
        if quote:
            log_record(to_token, quote, False, None, None)

    logger.info("[dev3] ✅ Цикл завершено")
    return any_accepted
