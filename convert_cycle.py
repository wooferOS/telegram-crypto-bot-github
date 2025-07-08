from convert_api import get_quote, accept_quote, is_valid_convert_pair
from convert_logger import logger, summary_logger, log_conversion_result


def process_pair(from_token: str, to_tokens, amount: float, score_threshold: float) -> bool:
    """Process available pairs for a single ``from_token``."""

    logger.info(f"[dev3] 🔍 Аналіз для {from_token} → {len(to_tokens)} токенів")
    success_count = 0

    for to_token in to_tokens:
        if not is_valid_convert_pair(from_token, to_token):
            logger.warning(f"[dev3] ❌ Пара {from_token} → {to_token} не підтримується Convert API")
            continue

        quote = get_quote(from_token, to_token, amount)
        if not quote or "quoteId" not in quote or "ratio" not in quote:
            logger.warning(f"[dev3] ❌ Не вдалося отримати валідний quote для {from_token} → {to_token}")
            continue

        score = float(quote.get("score", 0.0))
        if score < score_threshold:
            logger.info(f"[dev3] ⛔ Пропущено {from_token} → {to_token} через низький score={score:.4f}")
            continue

        result = accept_quote(quote["quoteId"])
        if result.get("status") == "SUCCESS":
            logger.info(f"[dev3] ✅ Конверсія {from_token} → {to_token} (score={score:.4f})")
            log_conversion_result(quote, accepted=True)
            success_count += 1
        else:
            logger.warning(f"[dev3] ❌ Конверсія {from_token} → {to_token} не пройшла: {result}")
            log_conversion_result(quote, accepted=False)

    skipped_count = len(to_tokens) - success_count
    summary_logger.info(f"Завершено цикл. Успішних: {success_count}, Пропущено: {skipped_count}")
    return success_count > 0
