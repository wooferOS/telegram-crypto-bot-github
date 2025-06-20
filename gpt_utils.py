import json
import logging
import openai
from config import OPENAI_API_KEY

client = openai.OpenAI(api_key=OPENAI_API_KEY)
logger = logging.getLogger(__name__)



def ask_gpt(payload: dict) -> dict:
    """Send ``payload`` to GPT and return JSON response."""

    try:
        logger.info(
            "[dev] ➡️ GPT input:\n%s",
            json.dumps(payload, indent=2, ensure_ascii=False),
        )

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ти професійний криптотрейдер. "
                        "Завжди поверни JSON з полями buy, sell, scores, summary."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=60,
        )

        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except Exception:
            logger.warning("[dev] ❌ GPT forecast is not JSON. Raw content:\n%s", content)
            return {"buy": [], "sell": [], "scores": {}, "summary": ""}

    except Exception as exc:  # noqa: BLE001
        logger.warning("[dev] GPT error: %s", exc)
        return {"buy": [], "sell": [], "scores": {}, "summary": ""}
