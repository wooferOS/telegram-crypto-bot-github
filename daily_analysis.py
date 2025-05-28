import os
import datetime
from dotenv import load_dotenv
from binance.client import Client
from openai import OpenAI

# Завантаження .env змінних
load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Ініціалізація клієнтів
binance_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

def get_wallet_summary():
    balances = binance_client.get_account()["balances"]
    non_zero_balances = [
        asset for asset in balances if float(asset["free"]) > 0
    ]
    summary_lines = [
        f"{asset['asset']}: {float(asset['free'])}" for asset in non_zero_balances
    ]
    return "\n".join(summary_lines)

def generate_gpt_report(wallet_summary: str) -> str:
    prompt = f"""
Ти професійний трейдер-аналітик. Нижче — мій крипто-портфель:

{wallet_summary}

Для кожного активу:
- оцінити перспективу (купити, тримати, продати);
- дати Stop Loss і Take Profit;
- не давати фінансових порад, лише технічний аналіз;
- написати коротко, чітко, як таблицю.
"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ти — аналітик криптовалют, надаєш короткий теханаліз."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Помилка GPT:\n\n{str(e)}"

def main():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

    print(f"📊 Щоденний звіт ({timestamp})\n")

    wallet_report = get_wallet_summary()
    print("💼 Поточний баланс Binance:")
    print(wallet_report + "\n")

    gpt_summary = generate_gpt_report(wallet_report)
    print("📈 GPT-аналітика:")
    print(gpt_summary + "\n")

    markdown = f"""# 📊 Щоденний звіт ({timestamp})

## 💼 Поточний баланс Binance:
