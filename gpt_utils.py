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
            f"- Що продаємо: {summary.get('sell') or summary.get('sell_candidates', [])}\n"
            f"- Що купуємо: {summary.get('buy') or summary.get('buy_candidates', [])}\n"
            f"- Очікуваний прибуток: {summary.get('total_profit') or summary.get('expected_profit', '')}\n"
            f"- Адаптивні фільтри: profit>={summary.get('adaptive_filters', {}).get('min_expected_profit')} prob>={summary.get('adaptive_filters', {}).get('min_prob_up')}\n"
            "scoreboard:\n"
            + "\n".join(summary.get('scoreboard', []))
            + "\n"
            "Відповідай строго у форматі JSON, без пояснень:\n"
            '{"buy": [...], "sell": [...], "scores": {...}}'
        )

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ти професійний криптотрейдер. "
                        "Навіть якщо немає великих прибутків, знайди топ-3 монети з потенціалом прибутку, "
                        "аналізуй дані, а не відповідай шаблоном. Завжди обирай найкращі доступні варіанти."
                    ),
                },
                {"role": "user", "content": content},
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
