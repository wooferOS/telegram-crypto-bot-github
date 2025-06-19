import json
import logging
import openai
from config import OPENAI_API_KEY

client = openai.OpenAI(api_key=OPENAI_API_KEY)


def ask_gpt(summary):
    try:
        content = (
            "Ти криптотрейдер. Оціни ситуацію:\n"
            f"- Баланс: {summary.get('balance', '')}\n"
            f"- Що продаємо: {summary.get('sell', [])}\n"
            f"- Що купуємо: {summary.get('buy', [])}\n"
            f"- Очікуваний прибуток: {summary.get('total_profit', '')}\n"
            "Відповідай строго у форматі JSON, без пояснень:\n"
            '{"buy": [...], "sell": [...], "scores": {...}}'
        )

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ти професійний криптотрейдер."},
                {"role": "user", "content": content}
            ],
            temperature=0.7,
            timeout=60
        )
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except Exception:
            logging.warning("[dev] GPT response is not JSON, skipping")
            return None

    except Exception as e:
        logging.warning(f"[dev] GPT error: {e}")
        return None
