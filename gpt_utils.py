from typing import Dict, Any

from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def ask_gpt(summary: Dict[str, Any]) -> str:
    """Send trading summary to GPT and return a short strategy forecast."""
    prompt = f"""
    Ти — GPT-аналітик крипторинку. На основі поточних даних знайди способи заробити за наступні 24 години, навіть якщо ринок слабкий. Якщо немає ідеальних умов, знайди найкращі з можливих.

Дані:
- Баланс (гривня, активи): {summary.get("balance", "")}
- Продати (PnL): {summary.get("recommended_sell", "")}
- Купити: {summary.get("recommended_buy", "")}
- Потенційний прибуток: {summary.get("profit", "")}
- Поточний стан ринку: {summary.get("market_trend", "")}

Обов'язково:
1. Визнач, яку стратегію було застосовано: ідеальний фільтр чи fallback.
2. Поясни, чому саме ці активи обрано для покупі або утримання.
3. Якщо ринок падає — запропонуй тактику short-term відскоку або перенесення входу.
4. Уникай фраз типу “нічого не купувати”. Завжди знайди оптимальну точку входу або підготовку.

Вивід: стисла стратегія у форматі прогнозу з логікою. Без вступів, без підписів.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "\u0422\u0438 \u0456\u043d\u0432\u0435\u0441\u0442-\u0430\u0441\u0438\u0441\u0442 \u0434\u043b\u044f \u043a\u0440\u0438\u043f\u0442\u043e\u0442\u0440\u0435\u0439\u0434\u0438\u043d\u0433\u0443."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"\u26a0\ufe0f GPT \u043f\u043e\u043c\u0438\u043b\u043a\u0430: {str(e)}"


__all__ = ["ask_gpt"]
