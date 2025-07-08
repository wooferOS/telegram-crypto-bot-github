def process_pair(from_token: str, available_to_tokens, amount: float, score_threshold: float):
    """Process available pairs for a single ``from_token``.

    Parameters
    ----------
    from_token: str
        Asset to convert from.
    available_to_tokens: Iterable[str]
        Tokens which are available to convert ``from_token`` to.
    amount: float
        Amount of ``from_token`` to use when requesting quotes.
    score_threshold: float
        Minimal score required for a quote to be executed.
    """

    from convert_api import get_quote, accept_quote
    from convert_logger import logger, summary_logger
    from convert_model import predict

    logger.info(f"[dev3] 🔍 Аналіз для {from_token} → {len(available_to_tokens)} токенів")
    best_quotes = []
    all_quotes = []

    for to_token in available_to_tokens:
        quote = get_quote(from_token, to_token, amount)
        if not quote:
            continue

        ratio = float(quote["ratio"])
        _, _, score = predict(from_token, to_token, quote)
        all_quotes.append({"to_token": to_token, "ratio": ratio, "score": score, "quote": quote})

        if score >= score_threshold:
            best_quotes.append({"to_token": to_token, "score": score, "quote": quote})

    if not best_quotes:
        logger.warning("[dev3] ⚠️ Fallback: жодна пара не пройшла фільтр. Обираємо top 2 за ratio.")
        quotes_sorted_by_ratio = sorted(all_quotes, key=lambda x: x["ratio"], reverse=True)
        best_quotes = quotes_sorted_by_ratio[:2]  # навіть якщо score == 0

    success_count = 0
    for item in best_quotes:
        to_token = item["to_token"]
        quote = item.get("quote")
        logger.info(f"[dev3] ✅ Конверсія {from_token} → {to_token} (score={item['score']:.4f})")
        if quote and "quoteId" in quote:
            accept_quote(quote["quoteId"])
        else:
            logger.warning("[dev3] ❌ Неможливо прийняти quote — відсутній quoteId або quote = None")
        success_count += 1

    skipped_count = len(available_to_tokens) - success_count
    summary_logger.info(f"Завершено цикл. Успішних: {success_count}, Пропущено: {skipped_count}")
