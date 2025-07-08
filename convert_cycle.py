from datetime import datetime
from typing import List, Dict, Tuple

from convert_api import get_quote, accept_quote
from convert_logger import (
    logger,
    save_convert_history,
)
from convert_model import predict
from convert_filters import filter_top_tokens


# Allow executing quotes with low score for model training
allow_learning_quotes = True


def process_pair(from_token: str, to_tokens: List[str], amount: float, score_threshold: float):
    logger.info(f"[dev3] 🔍 Аналіз для {from_token} → {len(to_tokens)} токенів")
    top_results: List[Tuple[str, float, Dict]] = []
    quotes_map: Dict[str, Dict] = {}
    scores: Dict[str, float] = {}
    all_tokens: Dict[str, Dict] = {}
    skipped_pairs: List[Tuple[str, float, str]] = []  # (token, score, reason)

    for to_token in to_tokens:
        quote = get_quote(from_token, to_token, amount)
        quotes_map[to_token] = quote
        if not quote or "ratio" not in quote:
            reason = "ratio_unavailable"
            logger.warning(
                f"[dev3] ❌ Не вдалося отримати ratio для {from_token} → {to_token}"
            )
            skipped_pairs.append((to_token, 0.0, reason))
            continue

        score = float(quote.get("score", 0))
        scores[to_token] = score
        all_tokens[to_token] = {"score": score, "quote": quote}
        if score < score_threshold:
            reason = f"low_score {score:.4f}"
            logger.info(
                f"[dev3] ⏭️ Пропуск {from_token} → {to_token}: {reason}"
            )
            skipped_pairs.append((to_token, score, reason))

    filtered_pairs = filter_top_tokens(all_tokens, score_threshold, top_n=2, fallback_n=1)
    top_results = [(t, data["score"], data["quote"]) for t, data in filtered_pairs]

    # Build opportunities list for post-processing
    convert_opportunities = [
        {"from": from_token, "to": t, "score": sc, "quote": q}
        for t, sc, q in top_results
    ]

    # 🧹 Remove duplicate 'from' tokens keeping highest score
    unique_ops = {}
    for op in convert_opportunities:
        key = op["from"]
        if key not in unique_ops or op["score"] > unique_ops[key]["score"]:
            unique_ops[key] = op

    convert_opportunities = list(unique_ops.values())

    top_results = [(op["to"], op["score"], op["quote"]) for op in convert_opportunities]

    # Log selection results
    if top_results:
        logger.info("[dev3] ✅ Обрано токени для купівлі: %s", [t for t, _, _ in top_results])
    else:
        logger.warning(
            "[dev3] ❌ Не знайдено жодного токена для купівлі навіть для навчальної угоди."
        )
        return

    selected_tokens = {t for t, _, _ in top_results}

    # Optionally process one low-score pair for training purposes
    training_candidate = None
    if allow_learning_quotes:
        for token, sc, _reason in skipped_pairs:
            quote = quotes_map.get(token)
            if quote and "quoteId" in quote:
                training_candidate = (token, sc, quote)
                break

    for to_token, score, quote in top_results:
        accept_result = None
        try:
            accept_result = accept_quote(quote["quoteId"])
            if accept_result:
                logger.info(f"[dev3] ✅ accept_quote успішний: {quote['quoteId']}")
            else:
                logger.warning(
                    f"[dev3] ❌ Помилка під час accept_quote: {quote['quoteId']} — {accept_result}"
                )
        except Exception as error:  # pragma: no cover - network/IO
            logger.warning(
                f"[dev3] ❌ Помилка під час accept_quote: {quote['quoteId']} — {error}"
            )
            accept_result = None

        accepted = bool(accept_result)

        logger.info(
            f"[dev3] {'✅' if accepted else '❌'} Конверсія {from_token} → {to_token} (score={score:.4f})"
        )

        record = {
            "from_token": from_token,
            "to_token": to_token,
            "score": score,
            "expected_profit": float(quote.get("expected_profit", 0)),
            "prob_up": float(quote.get("prob_up", 0)),
            "ratio": quote.get("ratio"),
            "from_amount": quote.get("fromAmount"),
            "to_amount": quote.get("toAmount"),
        }

        # Save accepted status only after real accept_quote call
        if accepted:
            record["accepted"] = True
        else:
            record["accepted"] = False

        save_convert_history(record)

    # Execute one additional low-score pair for training
    if training_candidate:
        to_token, score, quote = training_candidate
        selected_tokens.add(to_token)
        accept_result = None
        try:
            accept_result = accept_quote(quote["quoteId"])
            if accept_result:
                logger.info(
                    f"[dev3] 📊 Навчальна угода успішна: {quote['quoteId']}"
                )
            else:
                logger.warning(
                    f"[dev3] 📊 Навчальна угода помилка: {quote['quoteId']} — {accept_result}"
                )
        except Exception as error:  # pragma: no cover - network/IO
            logger.warning(
                f"[dev3] 📊 Навчальна угода помилка: {quote['quoteId']} — {error}"
            )
            accept_result = None

        accepted = bool(accept_result)
        logger.info(
            f"[dev3] {'✅' if accepted else '❌'} 📊 Навчальна угода {from_token} → {to_token} (score={score:.4f})"
        )

        record = {
            "from_token": from_token,
            "to_token": to_token,
            "score": score,
            "expected_profit": float(quote.get("expected_profit", 0)),
            "prob_up": float(quote.get("prob_up", 0)),
            "ratio": quote.get("ratio"),
            "from_amount": quote.get("fromAmount"),
            "to_amount": quote.get("toAmount"),
            "training": True,
            "accepted": accepted,
        }

        save_convert_history(record)

    # Log rejected pairs
    for to_token in to_tokens:
        if to_token in selected_tokens:
            continue
        quote = quotes_map.get(to_token)
        record = {"from_token": from_token, "to_token": to_token, "accepted": False}
        if quote and "ratio" in quote:
            record.update(
                {
                    "score": scores.get(to_token, 0.0),
                    "expected_profit": float(quote.get("expected_profit", 0)),
                    "prob_up": float(quote.get("prob_up", 0)),
                    "ratio": quote.get("ratio"),
                    "from_amount": quote.get("fromAmount"),
                    "to_amount": quote.get("toAmount"),
                }
            )
        save_convert_history(record)

    logger.info("[dev3] ✅ Цикл завершено")
