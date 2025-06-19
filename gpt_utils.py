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
            "Дай короткий коментар. Якщо нічого не купуємо чи не продаємо — скажи це."
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
        return response.choices[0].message.content.strip()

    except Exception as e:
        logging.warning(f"[dev] GPT error: {e}")
        return None
