from openai import OpenAI

client = OpenAI(api_key=OPENAI_API_KEY)

def generate_report():
    account = binance_client.get_account()
    balances = {a['asset']: float(a['free']) for a in account['balances'] if float(a['free']) > 0.0}
    print("📊 BALANCES:", balances)

    sorted_balances = dict(sorted(balances.items(), key=lambda x: x[1], reverse=True))
    total = sum(sorted_balances.values())

    prompt = f"""
🔍 Ти криптоаналітик. Проаналізуй портфель: {sorted_balances}
Сумарно: {total:.2f} монет.

📌 Завдання:
1. ТОП-3 монети за обсягом.
2. Чи портфель надто сконцентрований?
3. Що варто продати/докупити?
4. Таблиця Stop-Loss (%).
5. Три дії на сьогодні.
"""

    print("📨 PROMPT GPT:", prompt)

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()
