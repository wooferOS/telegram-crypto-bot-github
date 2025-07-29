import argparse
import asyncio
import json
import os
from typing import Callable, Dict, List, Optional

from convert_api import get_available_to_tokens, get_balances, sanitize_token_pair
from binance_api import get_spot_price, get_ratio
from convert_logger import logger
from convert_notifier import send_telegram, notify_fallback_model_warning
from gpt_utils import ask_gpt
from convert_model import predict, _load_model, is_fallback_model, safe_float
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

    try:
        for to_token in to_tokens:
            from_price = await asyncio.to_thread(get_spot_price, from_token)
            to_price = await asyncio.to_thread(get_spot_price, to_token)
            if from_price is None or to_price is None:
                logger.warning(
                    f"[dev3] ⚠️ Немає ціни для {from_token} або {to_token}"
                )
                continue

            if from_price == 0 or to_price == 0:
                logger.warning(
                    f"[dev3] ⛔️ Пропущено: ціна == 0 для {from_token} → {to_token}"
                )
                continue

            ratio = from_price / to_price
            inverse_ratio = to_price / from_price

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

            if is_fallback_model():
                score = 0.0

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
    except Exception as exc:  # pragma: no cover - network
        logger.error(f"[dev3] ❌ fetch_quotes() помилка для {from_token}: {exc}")
        return []

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
        if isinstance(items, list):
            predictions.extend(items)
        elif items:
            logger.warning(f"[dev3] ⚠️ fetch_quotes повернув не список: {items}")

    logger.info(f"[dev3] ✅ Загалом отримано {len(predictions)} прогнозів")
    return predictions


async def filter_valid_quotes(pairs: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """Return pairs that have sufficient balance and available prices."""
    valid_pairs: List[Dict[str, float]] = []
    for pair in pairs:
        from_token = pair.get("from_token")
        to_token = pair.get("to_token")
        if not from_token or not to_token:
            continue

        balance = get_token_balance(from_token)
        if balance == 0:
            continue

        from_price = await asyncio.to_thread(get_spot_price, from_token)
        to_price = await asyncio.to_thread(get_spot_price, to_token)
        if from_price is None or to_price is None:
            continue

        pair["amount"] = balance
        valid_pairs.append(pair)

    return valid_pairs


async def convert_mode() -> None:
    from binance_api import get_binance_balances

    try:
        model = _load_model()
        if is_fallback_model():
            notify_fallback_model_warning()
    except Exception:
        pass

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
        items.sort(key=lambda x: safe_float(x.get("score", 0)), reverse=True)
        top_tokens_by_score.extend(items[:10])

    # By default use score-based ranking
    top_tokens: List[Dict[str, float]] = top_tokens_by_score
    if top_tokens:
        top_tokens = await filter_valid_quotes(top_tokens)
        filtered: List[Dict[str, float]] = []
        for pair in top_tokens:
            if get_ratio("USDT", pair.get("to_token")) > 0:
                filtered.append(pair)
        top_tokens = filtered
    else:
        logger.warning(
            "[dev3] ❌ top_tokens.json порожній — відсутні релевантні прогнози"
        )

    for token in top_tokens:
        token["score"] = safe_float(token.get("score", 0))
        token["expected_profit"] = safe_float(token.get("expected_profit", 0))
        token["prob_up"] = safe_float(token.get("prob_up", 0))

    # 🧪 Timely logging of GPT forecast
    forecast_map = await ask_gpt(top_tokens, mode="convert")

    if isinstance(forecast_map, str):
        try:
            forecast_map = json.loads(forecast_map)
        except json.JSONDecodeError:
            logger.warning("\u274c GPT forecast is not valid JSON")
            forecast_map = {}

    if not forecast_map:
        print("❌ GPT forecast is empty or None — forecast_map:", forecast_map)
        os.makedirs("logs", exist_ok=True)
        with open("logs/convert_gpt.log", "a", encoding="utf-8") as f:
            f.write("❌ GPT forecast is empty or None\n")
        return
    else:
        os.makedirs("logs", exist_ok=True)
        with open("logs/convert_gpt.log", "w", encoding="utf-8") as f:
            json.dump(forecast_map, f, indent=2)

    for token in top_tokens:
        token_from = token.get("from") or token.get("from_token")
        token_to = token.get("to") or token.get("to_token")
        if not token_from or not token_to:
            continue
        pair_key = f"{token_from}->{token_to}"
        token["gpt"] = forecast_map.get(pair_key, {})

    prompt: str = json.dumps({"predictions": predictions}, ensure_ascii=False)
    forecast_text: Optional[str] = ""
    forecast_response = await ask_gpt(prompt)
    if forecast_response:
        try:
            forecast_json = json.loads(forecast_response)
            if isinstance(forecast_json, list):
                # Вставляємо GPT-прогноз у поле "gpt"
                enriched_tokens = []
                for gpt_item in forecast_json:
                    from_token = gpt_item.get("from")
                    to_token = gpt_item.get("to")
                    matching = [
                        t
                        for t in top_tokens
                        if t.get("from_token") == from_token
                        and t.get("to_token") == to_token
                    ]
                    if matching:
                        token = matching[0]
                        token["gpt"] = {
                            "score": gpt_item.get("score"),
                            "profit": gpt_item.get("profit"),
                            "prob_up": gpt_item.get("prob_up"),
                        }
                        enriched_tokens.append(token)
                top_tokens = enriched_tokens
                forecast_text = ""
            elif isinstance(forecast_json, dict) and "forecast_text" in forecast_json:
                forecast_text = forecast_json.get("forecast_text", "")
            else:
                forecast_text = forecast_response
        except Exception:
            forecast_text = forecast_response
    else:
        logger.warning(f"[dev3] ⚠️ GPT не повернув forecast_text. Prompt був: {prompt}")
        forecast_text = await ask_gpt(json.dumps(top_tokens_by_score, ensure_ascii=False))
        if not forecast_text:
            send_telegram("[dev3] ❌ GPT не згенерував прогноз для convert. Пропущено трейд.")

    top_tokens_path = os.path.join(os.path.dirname(__file__), "top_tokens.json")
    await asyncio.to_thread(save_json, top_tokens_path, top_tokens)

    gpt_forecast_path = os.path.join(os.path.dirname(__file__), "gpt_forecast.json")
    gpt_data = {
        "top": top_tokens,
        "raw": predictions,
        "forecast_text": forecast_text or "",
    }
    await asyncio.to_thread(save_json, gpt_forecast_path, gpt_data)

    from datetime import datetime

    # Зберегти forecast/convert_asia.json
    os.makedirs("forecast", exist_ok=True)
    forecast_path = os.path.join("forecast", "convert_asia.json")
    forecast_data = {
        "generated_at": datetime.utcnow().isoformat(),
        "forecast_text": forecast_text,
    }
    await asyncio.to_thread(save_json, forecast_path, forecast_data)

    # Додати лог у logs/forecast_convert.log
    os.makedirs("logs", exist_ok=True)
    with open("logs/forecast_convert.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.utcnow()}] ✅ Forecast saved to convert_asia.json\n")
        f.write(f"{forecast_text}\n\n")

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
