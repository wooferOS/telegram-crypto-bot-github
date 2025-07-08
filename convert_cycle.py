from datetime import datetime
from typing import List

from convert_api import get_quote, accept_quote
from convert_logger import (
    logger,
    save_convert_history,
)
from convert_model import predict


def process_pair(from_token: str, to_tokens: List[str], amount: float, score_threshold: float):
    logger.info(f"[dev3] 🔍 Аналіз для {from_token} → {len(to_tokens)} токенів")
    top_results = []

    for to_token in to_tokens:
        quote = get_quote(from_token, to_token, amount)
        if not quote or "ratio" not in quote:
            logger.warning(f"[dev3] ❌ Не вдалося отримати ratio для {from_token} → {to_token}")
            continue

        score = float(quote.get("score", 0))
        if score >= score_threshold:
            top_results.append((to_token, score, quote))

    if not top_results:
        logger.warning("[dev3] ⚠️ Fallback: жодна пара не пройшла фільтр. Обираємо top 2 за ratio.")
        fallback_quotes = []
        for to_token in to_tokens:
            quote = get_quote(from_token, to_token, amount)
            if quote and "ratio" in quote:
                fallback_quotes.append((to_token, float(quote["ratio"]), quote))
        fallback_quotes.sort(key=lambda x: x[1], reverse=True)
        top_results = [(x[0], 0.0, x[2]) for x in fallback_quotes[:2]]

    for to_token, score, quote in top_results:
        response = accept_quote(quote["quoteId"])
        accepted = response.get("status") == "success"

        logger.info(f"[dev3] {'✅' if accepted else '❌'} Конверсія {from_token} → {to_token} (score={score:.4f})")

        record = {
            "from_token": from_token,
            "to_token": to_token,
            "score": score,
            "expected_profit": float(quote.get("expected_profit", 0)),
            "prob_up": float(quote.get("prob_up", 0)),
            "ratio": quote.get("ratio"),
            "from_amount": quote.get("fromAmount"),
            "to_amount": quote.get("toAmount"),
            "accepted": accepted,
            "timestamp": datetime.utcnow().isoformat()
        }
        save_convert_history(record)

    logger.info("[dev3] ✅ Цикл завершено")
