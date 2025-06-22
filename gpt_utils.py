"""Utilities for working with GPT models."""

import json
import logging

from typing import Any, Optional

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


async def ask_gpt(messages: list, api_key: str) -> Optional[str]:
    import aiohttp

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if not isinstance(messages, list):
        messages = [messages]

    payload = {
        "model": "gpt-4o",
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 1200,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.warning(f"[dev] ⚠️ GPT API error {resp.status}: {await resp.text()}")
                    return None
    except Exception as e:
        logger.warning(f"[dev] ❌ GPT request failed: {e}")
        return None


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
