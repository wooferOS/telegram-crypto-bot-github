def process_pair(from_token, available_to_tokens, model, score_threshold):
    from convert_api import get_quote, accept_quote
    from convert_logger import logger
    from convert_notifier import log_conversion_response
    from convert_model import predict_score

    logger.info(f"[dev3] 🔍 Аналіз для {from_token} → {len(available_to_tokens)} токенів")
    successful = []
    fallback_candidates = []

    for to_token in available_to_tokens:
        quote = get_quote(from_token, to_token)
        if not quote:
            continue

        ratio = float(quote["ratio"])
        inverse_ratio = float(quote["inverseRatio"])
        features = [[ratio, inverse_ratio, 1.0]]  # dummy feature to match training
        score = predict_score(model, features)

        if score >= score_threshold:
            logger.info(f"[dev3] ✅ Конверсія {from_token} → {to_token} (score={score:.4f})")
            response = accept_quote(from_token, to_token)
            log_conversion_response(response)
            successful.append((to_token, score))
        else:
            logger.info(
                f"[dev3] ❌ Відмова: {from_token} → {to_token} — score {score:.4f} < threshold {score_threshold}"
            )
            fallback_candidates.append((to_token, score))

    # Якщо нічого не пройшло — fallback: топ-3 з найвищим score
    if not successful and fallback_candidates:
        fallback_candidates.sort(key=lambda x: x[1], reverse=True)
        top_fallbacks = fallback_candidates[:3]
        for to_token, score in top_fallbacks:
            logger.warning(f"[dev3] ⚠️ Fallback-конверсія {from_token} → {to_token} (score={score:.4f})")
            response = accept_quote(from_token, to_token)
            log_conversion_response(response)
