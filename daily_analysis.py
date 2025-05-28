import os
import datetime
from dotenv import load_dotenv
from openai import OpenAI
from binance.client import Client

# Завантажуємо змінні з .env
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

openai_client = OpenAI(api_key=OPENAI_API_KEY)
binance_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

# Отримуємо повний список активів
def get_wallet_assets():
    balances = binance_client.get_account()["balances"]
    wallet = {}
    for asset in balances:
        asset_name = asset["asset"]
        free_amount = float(asset["free"])
        if free_amount > 0:
            wallet[asset_name] = free_amount
    return wallet

# Формуємо Markdown-звіт балансу
def format_wallet(wallet: dict) -> str:
    lines = [f"{asset}: {amount}" for asset, amount in wallet.items()]
    return "\n".join(lines)

# Генеруємо GPT-аналітику
def generate_gpt_analysis(wallet_report: str) -> str:
    try:
        prompt = (
            f"Ось баланс криптогаманця на Binance:\n\n{wallet_report}\n\n"
            f"Проаналізуй ці активи і надай короткі поради щодо того, що доцільно продати, "
            f"що залишити, а що купити. Врахуй можливу волатильність, поточні тренди та ризики. "
            f"Додай рекомендації щодо стоп-лоссів і потенційного прибутку. "
            f"Напиши українською мовою, коротко та зрозуміло."
        )

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ти — досвідчений криптоаналітик."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=800,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"⚠️ Помилка GPT: {str(e)}"

# Головна функція генерації звіту
def main():
    print("📊 Генеруємо щоденний звіт...")

    today = datetime.date.today().isoformat()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    wallet = get_wallet_assets()
    wallet_report = format_wallet(wallet)
    gpt_summary = generate_gpt_analysis(wallet_report)

    markdown = f"""# 📊 Щоденний звіт ({timestamp})

💼 Поточний баланс Binance:
{wallet_report}

📈 GPT-аналітика:
{gpt_summary}
"""

    report_filename = f"daily_report_{today}.md"
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"✅ Звіт збережено у {report_filename}")

if __name__ == "__main__":
    main()
