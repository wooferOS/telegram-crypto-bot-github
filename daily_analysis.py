import asyncio
import os
from typing import Dict, List

from convert_api import get_balances, get_available_to_tokens, get_quote
from convert_logger import logger
from convert_model import predict
from utils_dev3 import save_json


async def fetch_quotes(from_token: str, amount: float) -> List[Dict[str, float]]:
    """Fetch quotes for all available to_tokens for a given from_token and run prediction."""
    predictions: List[Dict[str, float]] = []
    try:
        to_tokens = await asyncio.to_thread(get_available_to_tokens, from_token)
    except Exception as exc:
        logger.warning(f"[dev3] ❌ get_available_to_tokens помилка для {from_token}: {exc}")
        return predictions

    if not to_tokens:
        logger.warning(f"[dev3] ⚠️ Немає доступних to_token для {from_token}")
    else:
        logger.info(f"[dev3] 🔄 {from_token}: знайдено {len(to_tokens)} TO токенів")

    for to_token in to_tokens:
        try:
            quote = await asyncio.to_thread(get_quote, from_token, to_token, amount)
        except Exception as exc:
            logger.warning(f"[dev3] ❌ get_quote помилка для {from_token} → {to_token}: {exc}")
            continue

        logger.info(f"[dev3] 🔍 Quote {from_token} → {to_token}: {quote}")

        if not isinstance(quote, dict) or "ratio" not in quote:
            continue

        ratio = float(quote["ratio"])
        inverse_ratio = 1 / ratio if ratio != 0 else 0.0

        try:
            logger.info(f"[dev3] 🤖 predict() викликається для {from_token} → {to_token} з даними: {quote}")
            expected_profit, prob_up, score = predict(
                from_token,
                to_token,
                {"ratio": ratio, "inverseRatio": inverse_ratio},
            )
        except Exception as exc:
            logger.warning(f"[dev3] ❌ Помилка в predict() для {from_token} → {to_token}: {exc}")
            continue

        predictions.append({
            "from_token": from_token,
            "to_token": to_token,
            "ratio": ratio,
            "inverseRatio": inverse_ratio,
            "expected_profit": expected_profit,
            "prob_up": prob_up,
            "score": score,
        })

    logger.info(f"[dev3] ✅ Прогнозів для {from_token}: {len(predictions)}")
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
    if not top_tokens:
        logger.warning("[dev3] ❌ top_tokens.json порожній — відсутні релевантні прогнози")
    await asyncio.to_thread(save_json, "top_tokens.json", top_tokens)

    logger.info(f"[dev3] ✅ Аналіз завершено. Створено top_tokens.json з {len(top_tokens)} записами.")


if __name__ == "__main__":
    asyncio.run(main())
