"""Utilities for working with GPT models."""

import json
import logging


logger = logging.getLogger(__name__)


def ask_gpt(prompt_dict: dict, model: str = "gpt-4o") -> dict:
    """Send ``prompt_dict`` to GPT and return the JSON response."""

    from openai import OpenAI

    client = OpenAI()

    try:
        kwargs = {
            "model": model,
            "messages": [
                {"role": "user", "content": json.dumps(prompt_dict)}
            ],
        }

        if model in ("gpt-4o", "gpt-4-turbo"):
            kwargs["response_format"] = "json"

        response = client.chat.completions.create(**kwargs)

        if hasattr(response, "error"):
            logger.error(f"[dev] GPT API error: {response.error}")
            return {}

        content = response.choices[0].message.content

        if isinstance(content, dict):
            return content

        return json.loads(content)

    except Exception as e:  # noqa: BLE001
        logger.exception(f"[dev] GPT fallback error: {e}")
        return {}
