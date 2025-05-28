import os
from openai import OpenAI
from binance.client import Client
from dotenv import load_dotenv
from datetime import datetime

# Завантаження .env
load_dotenv()

# Ініціалізація
binance_client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Отримання балансу
balances = binance_client.get_account()["balances"]
wallet_summary = "\n".join(
    [f"{asset['asset']}: {float(asset['free'])}" for asset in balances if float(asset["free"]) > 0]
)

# Формування тексту
now = datetime.now().strftime("%d.%m.%Y %H:%M")
report_text = f"📊 Щоденний звіт ({now})\n\n"
report_text += f"💼 Поточний баланс Binance:\n{wallet_summary}\n\n"

# Формування prompt до GPT
prompt = f"""
Це мій криптовалютний портфель:
{wallet_summary}

Зроби короткий технічний аналіз: що виглядає перспективно для купівлі або продажу?
Додай Stop Loss і Take Profit, якщо доречно.

Не давай фінансову пораду — лише технічну оцінку.
"""

# GPT-відповідь
try:
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Ти — аналітик криптовалют."},
            {"role": "user", "content": prompt}
        ]
    )
    gpt_reply = response.choices[0].message.content.strip()
    report_text += f"📈 GPT-аналітика:\n{gpt_reply}\n"
except Exception as e:
    report_text += f"📈 GPT-аналітика:\n❌ Помилка: {str(e)}\n"

# Збереження у файл
filename = f"daily_report_{datetime.now().strftime('%Y-%m-%d')}.md"
with open(filename, "w") as file:
    file.write(report_text)

# Вивід
print(report_text)
