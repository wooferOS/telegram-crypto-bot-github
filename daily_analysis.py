import asyncio
import os
from typing import Dict, List

from convert_api import get_balances, get_available_to_tokens, get_quote
from convert_logger import logger
from convert_model import predict
from utils_dev3 import save_json, get_current_timestamp
from top_tokens_utils import save_for_region, TOP_TOKENS_VERSION


async def fetch_quotes(from_token: str, amount: float) -> List[Dict[str, float]]:
    """Fetch quotes for all available to_tokens for given from_token."""
    predictions: List[Dict[str, float]] = []
    try:
        to_tokens = await asyncio.to_thread(get_available_to_tokens, from_token)
        logger.info(f"[dev3] 📥 Доступні to_tokens для {from_token}: {to_tokens}")
    except Exception as exc:
        logger.warning(
            f"[dev3] ❌ get_available_to_tokens помилка для {from_token}: {exc}"
        )
        return predictions

    for to_token in to_tokens:
        try:
            quote = await asyncio.to_thread(get_quote, from_token, to_token, amount)
            logger.info(
                f"[dev3] 🔄 Quote для {from_token} → {to_token}: {quote}"
            )
        except Exception as exc:
            logger.warning(
                f"[dev3] ❌ get_quote помилка для {from_token} → {to_token}: {exc}"
            )
            continue

        if not quote or "ratio" not in quote or "inverseRatio" not in quote:
            logger.warning(
                f"[dev3] ⛔️ Неповний quote для {from_token} → {to_token}: {quote}"
            )
            continue

        ratio = float(quote["ratio"])
        inverse_ratio = float(quote["inverseRatio"])

        base_expected_profit = ratio - 1.0
        base_prob_up = 0.5
        base_score = base_expected_profit * base_prob_up

        expected_profit, prob_up, score = predict(
            from_token,
            to_token,
            {
                "expected_profit": base_expected_profit,
                "prob_up": base_prob_up,
                "score": base_score,
                "ratio": ratio,
                "inverseRatio": inverse_ratio,
                "amount": amount,
            },
        )

        logger.info(
            f"[dev3] ✅ Прогноз: {from_token} → {to_token} | profit={expected_profit}, prob_up={prob_up}, score={score}"
        )

        predictions.append(
            {
                "from_token": from_token,
                "to_token": to_token,
                "ratio": ratio,
                "inverseRatio": inverse_ratio,
                "expected_profit": expected_profit,
                "prob_up": prob_up,
                "score": score,
            }
        )

    return predictions


async def gather_predictions() -> List[Dict[str, float]]:
    """Collect predictions for all tokens from account balances."""
    try:
        balances = await asyncio.to_thread(get_balances)
    except Exception as exc:
        logger.warning(f"[dev3] ❌ get_balances помилка: {exc}")
        return []

    logger.info(f"[dev3] 🔄 Отримано {len(balances)} токенів з балансу")

    tasks = [fetch_quotes(token, amount) for token, amount in balances.items()]
    results = await asyncio.gather(*tasks)

    predictions: List[Dict[str, float]] = []
    for items in results:
        predictions.extend(items)

    logger.info(f"[dev3] ✅ Загалом отримано {len(predictions)} прогнозів")
    return predictions


async def main() -> None:
    predictions = await gather_predictions()

    os.makedirs("logs", exist_ok=True)
    await asyncio.to_thread(save_json, os.path.join("logs", "predictions.json"), predictions)

    sorted_tokens = sorted(predictions, key=lambda x: x["score"], reverse=True)
    top_tokens = sorted_tokens[:5]
    region = os.environ.get("REGION", "ASIA").upper()
    if not top_tokens:
        logger.warning(
            "[dev3] ❌ top_tokens порожній — відсутні релевантні прогнози"
        )
        return

    pairs = [
        {
            "from": t["from_token"],
            "to": t["to_token"],
            "score": t.get("score"),
            "edge": t.get("expected_profit"),
        }
        for t in top_tokens
    ]

    data = {
        "version": TOP_TOKENS_VERSION,
        "region": region,
        "generated_at": get_current_timestamp(),
        "pairs": pairs,
    }
    await asyncio.to_thread(save_for_region, data, region)

    logger.info(
        f"[dev3] ✅ Аналіз завершено. Створено top_tokens для регіону {region} з {len(pairs)} записами."
    )


if __name__ == "__main__":
    asyncio.run(main())
