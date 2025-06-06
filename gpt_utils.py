import os
import time
import logging
from typing import List, Dict

import openai

openai.api_key = os.getenv("OPENAI_API_KEY")
logger = logging.getLogger(__name__)


def call_chat_completion(messages: List[Dict[str, str]], model: str = "gpt-4", retries: int = 3, delay: float = 2.0) -> str:
    """Call OpenAI chat completion with basic retry logic."""
    for attempt in range(retries):
        try:
            response = openai.ChatCompletion.create(model=model, messages=messages)
            return response["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # pragma: no cover - network call
            logger.warning("GPT error on attempt %s: %s", attempt + 1, exc)
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                logger.error("GPT failed after %s attempts: %s", retries, exc)
                return f"[GPT Error] {exc}"


def generate_investor_summary(balance: List[str], sells: List[str], buys: List[str]) -> str:
    """Create investor summary message via GPT."""
    prompt = (
        "\u0421\u0444\u043e\u0440\u043c\u0443\u0439 \u043a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 \u0456\u043d\u0432\u0435\u0441\u0442\u043e\u0440\u0441\u044c\u043a\u0438\u0439 \u043f\u0440\u043e\u0433\u043d\u043e\u0437 \u043d\u0430 \u043e\u0441\u043d\u043e\u0432\u0456:\n\n"
        f"\u0411\u0430\u043b\u0430\u043d\u0441:\n{balance}\n\n"
        f"\u041f\u0440\u043e\u0434\u0430\u0442\u0438:\n{sells}\n\n"
        f"\u041a\u0443\u043f\u0438\u0442\u0438:\n{buys}\n"
    )
    messages = [{"role": "user", "content": prompt}]
    return call_chat_completion(messages)



def generate_gpt_summary(prompt: str) -> str:
    """Generate short GPT summary from provided text."""
    messages = [{"role": "user", "content": prompt}]
    return call_chat_completion(messages)
