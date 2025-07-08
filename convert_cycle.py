def process_pair(from_token, available_to_tokens, model, score_threshold):
    from convert_api import get_quote, accept_quote
    from convert_logger import logger, summary_logger
    from convert_model import predict

    logger.info(f"[dev3] 🔍 Аналіз для {from_token} → {len(available_to_tokens)} токенів")
    best_quotes = []
    all_quotes = []

    for to_token in available_to_tokens:
        quote = get_quote(from_token, to_token)
        if not quote:
            continue

        ratio = float(quote["ratio"])
        _, _, score = predict(from_token, to_token, quote)
        all_quotes.append({"to_token": to_token, "ratio": ratio, "score": score})

        if score >= score_threshold:
            best_quotes.append({"to_token": to_token, "score": score})

    if not best_quotes:
        logger.warning("[dev3] ⚠️ Fallback: жодна пара не пройшла фільтр. Обираємо top 2 за ratio.")
        quotes_sorted_by_ratio = sorted(all_quotes, key=lambda x: x["ratio"], reverse=True)
        best_quotes = quotes_sorted_by_ratio[:2]  # навіть якщо score == 0

    success_count = 0
    for item in best_quotes:
        to_token = item["to_token"]
        logger.info(f"[dev3] ✅ Конверсія {from_token} → {to_token} (score={item['score']:.4f})")
        accept_quote(from_token, to_token)
        success_count += 1

    skipped_count = len(available_to_tokens) - success_count
    summary_logger.info(f"Завершено цикл. Успішних: {success_count}, Пропущено: {skipped_count}")
