import os
from dotenv import load_dotenv
from binance.client import Client
from openai import OpenAI
import requests

# --- Завантаження змінних ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# --- Ініціалізація клієнтів ---
client = OpenAI(api_key=OPENAI_API_KEY)
binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# --- Генерація GPT-звіту ---
def generate_report():
    account = binance_client.get_account()
    balances = {a['asset']: float(a['free']) for a in account['balances'] if float(a['free']) > 0.0}
    print("📊 BALANCES:", balances)

    sorted_balances = dict(sorted(balances.items(), key=lambda x: x[1], reverse=True))
    total = sum(sorted_balances.values())

    prompt = f"""
🔍 Ти криптоаналітик. Проаналізуй портфель користувача:
{sorted_balances}
Сумарна кількість активів: {total:.2f}

Структура звіту:
1. ТОП-3 монети за кількістю та відсотком у портфелі.
2. Диверсифікація: чи портфель збалансований?
3. Які 2 монети варто продати? Які 2 купити? Чому?
4. Таблиця Stop-Loss у %, приклад:
   | Монета | Кількість | Stop-Loss (%) |
5. Підсумкові рекомендації (3 дії на сьогодні).

Форматуй у Markdown.
"""

    print("📨 PROMPT GPT:", prompt)

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

# --- Збереження звіту ---
def save_report(text):
    with open("daily_report.txt", "w") as f:
        f.write(text)
    with open("daily.log", "a") as log:
        log.write(text + "\n\n")

# --- Надсилання в Telegram ---
def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": ADMIN_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=data)

# --- Основна логіка ---
if __name__ == "__main__":
    try:
        report = generate_report()
        print(report)
        save_report(report)
        send_to_telegram(report)
        send_to_telegram("✅ *Daily analysis script completed*. Перевір файл `daily.log`.")
    except Exception as e:
        print(f"❌ ERROR: {e}")
        send_to_telegram(f"❌ *GPT-Звіт не згенеровано:* `{e}`")
