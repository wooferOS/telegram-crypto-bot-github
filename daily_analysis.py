import argparse
import asyncio
import json
import os
from typing import Callable, Dict, List, Optional

from convert_api import get_available_to_tokens, get_quote, get_balances
from convert_logger import logger
from convert_notifier import send_telegram
from gpt_utils import ask_gpt
from convert_model import predict
from utils_dev3 import save_json

_balance_cache: Dict[str, float] | None = None


def get_token_balance(token: str) -> float:
    """Return balance for a token using cached balances."""
    global _balance_cache
    if _balance_cache is None:
        try:
            _balance_cache = get_balances()
        except Exception as exc:  # pragma: no cover - network
            logger.warning(f"[dev3] ❌ get_token_balance помилка: {exc}")
            _balance_cache = {}
    return float(_balance_cache.get(token, 0))


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
            logger.info(f"[dev3] 🔄 Quote для {from_token} → {to_token}: {quote}")
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


async def gather_predictions(
    get_balances_func: Callable[[], Dict[str, float]],
) -> List[Dict[str, float]]:
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
    """Return only pairs that have a valid quote via Convert API with fallback."""
    valid_pairs: List[Dict[str, float]] = []
    for pair in pairs:
        from_token = pair.get("from_token")
        to_token = pair.get("to_token")
        if not from_token or not to_token:
            continue

        balance = get_token_balance(from_token)
        if balance == 0:
            continue

        for factor in [1.0, 0.5, 0.25, 0.1]:
            test_amount = balance * factor
            try:
                quote = await asyncio.to_thread(
                    get_quote, from_token, to_token, test_amount
                )
                if quote and "quoteId" in quote:
                    pair["amount"] = test_amount
                    valid_pairs.append(pair)
                    logger.debug(
                        f"[dev3] ✅ valid quote {from_token} → {to_token} @ {test_amount}"
                    )
                    break
                else:
                    logger.debug(
                        f"[dev3] ❌ invalid quote for {from_token} → {to_token} @ {test_amount}: {quote}"
                    )
            except Exception as e:
                logger.debug(
                    f"[dev3] ❌ error for quote {from_token} → {to_token} @ {test_amount}: {str(e)}"
                )

    return valid_pairs


async def convert_mode() -> None:
    from binance_api import get_binance_balances

    predictions = await gather_predictions(get_binance_balances)

    os.makedirs("logs", exist_ok=True)
    await asyncio.to_thread(
        save_json, os.path.join("logs", "predictions.json"), predictions
    )

    grouped: Dict[str, List[Dict[str, float]]] = {}
    for item in predictions:
        grouped.setdefault(item["from_token"], []).append(item)

    top_tokens_by_score: List[Dict[str, float]] = []
    for items in grouped.values():
        items.sort(key=lambda x: x["score"], reverse=True)
        top_tokens_by_score.extend(items[:10])

    # By default use score-based ranking
    top_tokens: List[Dict[str, float]] = top_tokens_by_score
    if top_tokens:
        top_tokens = await filter_valid_quotes(top_tokens)
    else:
        logger.warning(
            "[dev3] ❌ top_tokens.json порожній — відсутні релевантні прогнози"
        )

    prompt: str = json.dumps({"predictions": predictions}, ensure_ascii=False)
    forecast_text: Optional[str] = await ask_gpt(prompt)
    if not forecast_text:
        logger.warning(f"[dev3] ⚠️ GPT не повернув forecast_text. Prompt був: {prompt}")
        forecast_text = await ask_gpt(
            json.dumps(top_tokens_by_score, ensure_ascii=False)
        )
        if not forecast_text:
            send_telegram(
                "[dev3] ❌ GPT не згенерував прогноз для convert. Пропущено трейд."
            )

    top_tokens_path = os.path.join(os.path.dirname(__file__), "top_tokens.json")
    await asyncio.to_thread(save_json, top_tokens_path, top_tokens)

    gpt_forecast_path = os.path.join(os.path.dirname(__file__), "gpt_forecast.json")
    gpt_data = {
        "top": top_tokens,
        "raw": predictions,
        "forecast_text": forecast_text or "",
    }
    await asyncio.to_thread(save_json, gpt_forecast_path, gpt_data)

    if top_tokens:
        first = top_tokens[0]
        example = f"{first.get('from_token')} → {first.get('to_token')} (score={first.get('score', 0):.4f})"
    else:
        example = "<empty>"
    with open("logs/gpt_convert.log", "a", encoding="utf-8") as f:
        f.write(f"[dev3] GPT-аналітика завершена\n")
        f.write(f"Рекомендації: {len(top_tokens)}\n")
        f.write(f"Приклад: {example}\n")
        if forecast_text:
            f.write(f"Forecast: {forecast_text}\n")

    logger.info(
        f"[dev3] ✅ Аналіз завершено. Створено top_tokens.json з {len(top_tokens)} записами."
    )


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
