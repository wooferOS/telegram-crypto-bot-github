import os
from binance.client import Client
from datetime import datetime
from openai import OpenAI

# Завантаження змінних з .env
from dotenv import load_dotenv
load_dotenv()

# Binance API
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

# OpenAI API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Telegram Chat ID (опціонально)
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Ініціалізація клієнтів
binance_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

def get_wallet_report():
    balances = binance_client.get_account()["balances"]
    wallet_lines = []
    for asset in balances:
        free = float(asset["free"])
        if free > 0:
            formatted = f"{asset['asset']}: {free}"
            wallet_lines.append(formatted)
    return "\n".join(wallet_lines)

def generate_gpt_report(wallet_text: str):
    prompt = f"""
Це мій криптовалютний портфель:
{wallet_text}

Зроби короткий технічний аналіз на основі цього портфеля. Що виглядає перспективно на купівлю або продаж? Додай Stop Loss і Take Profit для кожного активу, якщо доречно.

Не давай фінансових порад — лише технічний аналіз на основі поточної ситуації.
"""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ти — аналітик криптовалют."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Помилка: {e}"

def main():
    print("📊 Генеруємо щоденний звіт...")

    today = datetime.today().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%d.%m.%Y %H:%M')

    # Отримання балансу
    wallet_report = get_wallet_report()

    # Отримання GPT аналізу
    gpt_summary = generate_gpt_report(wallet_report)

    # Формування звіту
    markdown = f"""# 📊 Щоденний звіт ({timestamp})

## 💼 Поточний баланс Binance:
{wallet_report}

## 📈 GPT-аналітика:
{gpt_summary}
"""

    report_filename = f"daily_report_{today}.md"
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"✅ Звіт збережено у {report_filename}")

if __name__ == "__main__":
    main()
