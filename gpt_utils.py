from typing import Dict, Any, Optional

import logging
import openai
from config import OPENAI_API_KEY

openai.api_key = OPENAI_API_KEY


def ask_gpt(summary: Dict[str, Any]) -> Optional[str]:
    """Send trading summary to GPT and return a short strategy forecast."""
    try:
        prompt = (
            "\ud83d\udd0d \u041f\u0440\u043e\u0430\u043d\u0430\u043b\u0456\u0437\u0443\u0439 \u0441\u0438\u0442\u0443\u0430\u0446\u0456\u044e:\n"
            f"- \u0411\u0430\u043b\u0430\u043d\u0441: {summary.get('balance', '')}\n"
            f"- \u0429\u043e \u043f\u0440\u043e\u0434\u0430\u0454\u043c\u043e: {summary.get('sell', '')}\n"
            f"- \u0429\u043e \u043a\u0443\u043f\u0443\u0454\u043c\u043e: {summary.get('buy', '')}\n"
            f"- \u041e\u0447\u0456\u043a\u0443\u0432\u0430\u043d\u0438\u0439 \u043f\u0440\u0438\u0431\u0443\u0442\u043e\u043a: {summary.get('total_profit', '')}\n"
            "\u042f\u043a\u0456 \u0454 \u0432\u0438\u0441\u043d\u043e\u0432\u043a\u0438 \u0430\u0431\u043e \u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0456\u0457?"
        )
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            timeout=60,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:  # noqa: BLE001
        logging.warning("[dev] GPT error: %s", e)
        return None


__all__ = ["ask_gpt"]
