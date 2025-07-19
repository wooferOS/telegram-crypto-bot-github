import argparse
import asyncio
import os
from typing import Callable, Dict, List

from convert_api import get_available_to_tokens, get_quote
from convert_logger import logger
from convert_model import predict
from utils_dev3 import save_json


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


async def gather_predictions(get_balances_func: Callable[[], Dict[str, float]]) -> List[Dict[str, float]]:
    """Collect predictions for all tokens from provided balance function."""
    try:
        balances = await asyncio.to_thread(get_balances_func)
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


async def filter_valid_quotes(pairs: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """Return only pairs that have a valid quote via Convert API."""
    valid: List[Dict[str, float]] = []
    for item in pairs:
        from_token = item.get("from_token")
        to_token = item.get("to_token")
        if not from_token or not to_token:
            continue
        try:
            quote = await asyncio.to_thread(get_quote, from_token, to_token, 1)
        except Exception as exc:  # pragma: no cover - network
            logger.warning(
                f"[dev3] ❌ filter_valid_quotes помилка для {from_token} → {to_token}: {exc}"
            )
            continue

        if quote and "ratio" in quote:
            valid.append(item)
        else:
            logger.warning(
                f"[dev3] ⏭️ Пара {from_token} → {to_token} пропущена через відсутній quote: {quote}"
            )

    return valid


async def convert_mode() -> None:
    from binance_api import get_binance_balances

    predictions = await gather_predictions(get_binance_balances)

    os.makedirs("logs", exist_ok=True)
    await asyncio.to_thread(save_json, os.path.join("logs", "predictions.json"), predictions)

    grouped: Dict[str, List[Dict[str, float]]] = {}
    for item in predictions:
        grouped.setdefault(item["from_token"], []).append(item)

    top_tokens: List[Dict[str, float]] = []
    for items in grouped.values():
        items.sort(key=lambda x: x["score"], reverse=True)
        top_tokens.extend(items[:10])

    if top_tokens:
        top_tokens = await filter_valid_quotes(top_tokens)
    else:
        logger.warning("[dev3] ❌ top_tokens.json порожній — відсутні релевантні прогнози")

    top_tokens_path = os.path.join(os.path.dirname(__file__), "top_tokens.json")
    await asyncio.to_thread(save_json, top_tokens_path, top_tokens)

    gpt_forecast_path = os.path.join(os.path.dirname(__file__), "gpt_forecast.json")
    await asyncio.to_thread(save_json, gpt_forecast_path, predictions)

    logger.info(f"[dev3] ✅ Аналіз завершено. Створено top_tokens.json з {len(top_tokens)} записами.")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="convert")
    args = parser.parse_args()

    if args.mode == "convert":
        await convert_mode()
    else:
        logger.error("[dev3] Unsupported mode: %s", args.mode)


if __name__ == "__main__":
    asyncio.run(main())
