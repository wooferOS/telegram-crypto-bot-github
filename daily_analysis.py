import os
from typing import List, Dict

from convert_api import get_balances, get_available_to_tokens, get_quote
from convert_model import predict
from convert_logger import logger
from utils_dev3 import save_json


def main() -> None:
    balances = get_balances()
    predictions: List[Dict[str, float]] = []

    for from_token, amount in balances.items():
        to_tokens = get_available_to_tokens(from_token)
        for to_token in to_tokens:
            try:
                quote = get_quote(from_token, to_token, amount)
            except Exception as exc:  # pragma: no cover - network/IO
                logger.warning(
                    f"[dev3] ❌ get_quote помилка для {from_token} → {to_token}: {exc}"
                )
                continue

            if not isinstance(quote, dict) or "ratio" not in quote:
                continue

            ratio = float(quote.get("ratio", 0))
            inverse_ratio = float(quote.get("inverseRatio", 0))

            expected_profit, prob_up, score = predict(
                from_token, to_token, {"ratio": ratio, "inverseRatio": inverse_ratio}
            )

            predictions.append(
                {
                    "from_token": from_token,
                    "to_token": to_token,
                    "ratio": ratio,
                    "score": score,
                    "expected_profit": expected_profit,
                    "prob_up": prob_up,
                }
            )

    os.makedirs("logs", exist_ok=True)
    save_json(os.path.join("logs", "predictions.json"), predictions)

    # Select top 5 tokens by score
    sorted_tokens = sorted(predictions, key=lambda x: x["score"], reverse=True)
    top_tokens = [
        {
            "from_token": item["from_token"],
            "to_token": item["to_token"],
            "score": item["score"],
            "expected_profit": item["expected_profit"],
            "prob_up": item["prob_up"],
        }
        for item in sorted_tokens[:5]
    ]

    save_json("top_tokens.json", top_tokens)
    logger.info(
        f"[dev3] ✅ Аналіз завершено. Створено top_tokens.json з {len(top_tokens)} записами."
    )


if __name__ == "__main__":
    main()
