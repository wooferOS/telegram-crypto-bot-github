"""Utilities for working with GPT models."""

import json
import logging

from typing import Any

from binance_api import notify_telegram


logger = logging.getLogger(__name__)


DEFAULT_RESULT = {"buy": [], "sell": [], "scores": {}, "summary": ""}


def _ensure_structure(data: dict) -> dict:
    """Return ``data`` with required keys populated."""

    result = DEFAULT_RESULT.copy()
    if not isinstance(data, dict):
        return result
    result.update({k: data.get(k, result[k]) for k in result})
    return result


def ask_gpt(prompt_dict: dict, model: str = "gpt-4o") -> dict:
    """Send ``prompt_dict`` to GPT and return the JSON response."""

    from openai import OpenAI
    from config import OPENAI_API_KEY

    kwargs = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Please return a valid JSON object with fields: buy, sell, scores, summary.\n\n"
                    + json.dumps(prompt_dict)
                ),
            }
        ],
    }

    if model in ("gpt-4o", "gpt-4-turbo"):
        kwargs["response_format"] = {"type": "json_object"}

    try:
        with OpenAI(api_key=OPENAI_API_KEY) as client:
            response = client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[GPT] API request failed: %s", exc)
        notify_telegram(f"[GPT] ❌ Error: {exc}")
        return DEFAULT_RESULT.copy()

    if hasattr(response, "error") and response.error:
        logger.error("[GPT] API error: %s", response.error)
        notify_telegram(f"[GPT] ❌ Error: {response.error}")
        return DEFAULT_RESULT.copy()

    content: Any = response.choices[0].message.content

    if isinstance(content, dict):
        return _ensure_structure(content)

    try:
        parsed = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        logger.error("[GPT] Parsing failed: %s", exc)
        notify_telegram(f"[GPT] ❌ Error: {exc}")
        error_data = DEFAULT_RESULT.copy()
        error_data["summary"] = "GPT error: parsing failed"
        try:
            with open("gpt_forecast.txt", "w", encoding="utf-8") as f:
                json.dump(error_data, f, indent=2, ensure_ascii=False)
        except OSError as write_exc:  # pragma: no cover - diagnostics only
            logger.warning("Could not write gpt_forecast.txt: %s", write_exc)
        return error_data

    return _ensure_structure(parsed)


def get_gpt_forecast() -> dict:
    """Return GPT forecast from ``gpt_forecast.txt``.

    If the file is missing or invalid, an empty forecast structure is
    returned without raising an exception.
    """

    empty: dict = {"recommend_buy": [], "do_not_buy": []}
    try:
        with open("gpt_forecast.txt", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.warning("[dev] Could not read gpt_forecast.txt: %s", exc)
        return empty

    if not isinstance(data, dict):
        return empty

    rec_buy = data.get("recommend_buy") or data.get("buy") or []
    do_not_buy = data.get("do_not_buy") or data.get("sell") or []

    if not isinstance(rec_buy, list):
        rec_buy = []
    if not isinstance(do_not_buy, list):
        do_not_buy = []

    return {"recommend_buy": rec_buy, "do_not_buy": do_not_buy}


def save_predictions(predictions: dict) -> None:
    """Save ``predictions`` to ``logs/predictions.json``."""

    with open("logs/predictions.json", "w") as f:
        json.dump(predictions, f, indent=2)
