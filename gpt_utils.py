import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


async def ask_gpt(prompt: str, model: str = "gpt-4o") -> Optional[str]:
    """Send ``prompt`` to OpenAI and return the response text.

    Returns ``None`` if the request fails or the library is unavailable.
    """
    try:
        from openai import AsyncOpenAI
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning("[dev3] ❌ openai import error: %s", exc)
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("[dev3] ❌ OPENAI_API_KEY not set")
        return None

    client = AsyncOpenAI(api_key=api_key)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
    except Exception as exc:  # pragma: no cover - network
        logger.warning("[dev3] ❌ GPT request failed: %s", exc)
        return None

    try:
        content = response.choices[0].message.content
    except Exception as exc:  # pragma: no cover - response
        logger.warning("[dev3] ❌ GPT response parse error: %s", exc)
        return None

    return content.strip() if content else None
