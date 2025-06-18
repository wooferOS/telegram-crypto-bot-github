from typing import Dict, Any, Optional

import logging

from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def ask_gpt(summary: Dict[str, Any]) -> Optional[str]:
    """Send trading summary to GPT and return a short strategy forecast."""
    prompt = f"""
    Ти — GPT-аналітик крипторинку. Сформуй три сценарії: агресивний, обережний та fallback.
    Додай причини можливого продажу і причини утриматись від входу.

Дані:
- Баланс: {summary.get('balance', '')}
- Кандидати на продаж: {', '.join(summary.get('sell_candidates', []))}
- Кандидати на купівлю: {', '.join(summary.get('buy_candidates', []))}
- Очікуваний прибуток: {summary.get('expected_profit', '')}
- Тренд ринку: {summary.get('market_trend', '')}
- Стратегія: {summary.get('strategy', '')}

Формат виходу: короткий прогноз у 3 сценаріях без вступів і підписів.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "\u0422\u0438 \u0456\u043d\u0432\u0435\u0441\u0442-\u0430\u0441\u0438\u0441\u0442 \u0434\u043b\u044f \u043a\u0440\u0438\u043f\u0442\u043e\u0442\u0440\u0435\u0439\u0434\u0438\u043d\u0433\u0443."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=500,
            timeout=15,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:  # noqa: BLE001
        logging.warning(f"[dev] GPT error: {e}")
        return None


__all__ = ["ask_gpt"]
