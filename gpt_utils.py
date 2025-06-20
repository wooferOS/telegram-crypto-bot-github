import json
import logging
import openai
from config import OPENAI_API_KEY

client = openai.OpenAI(api_key=OPENAI_API_KEY)
logger = logging.getLogger(__name__)



def ask_gpt(summary):
    try:
        logger.info(
            f"[dev] ➡️ GPT input:\n{json.dumps(summary, indent=2, ensure_ascii=False)}"
        )

        balance_field = summary.get("balance", "")
        if isinstance(balance_field, dict):
            balance = ", ".join(
                f"{k}: {v}" for k, v in balance_field.items() if v
            )
        else:
            balance = balance_field

        content = (
            "Ти криптотрейдер. Оціни ситуацію:\n"
            f"- Баланс: {balance}\n"
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
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=60,
        )
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except Exception:
            logger.warning(
                f"[dev] ❌ GPT forecast is not JSON. Raw content:\n{content}"
            )
            return {"buy": [], "sell": [], "scores": {}}

    except Exception as e:
        logger.warning(f"[dev] GPT error: {e}")
        return {"buy": [], "sell": [], "scores": {}}
