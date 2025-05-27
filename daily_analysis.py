
import os
import json
from dotenv import load_dotenv
from binance.client import Client
import openai
import requests

# --- Ініціалізація змінних ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

openai.api_key = OPENAI_API_KEY
binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# --- Формування GPT-звіту ---
def generate_report():
    account = binance_client.get_account()
    balances = {a['asset']: a['free'] for a in account['balances'] if float(a['free']) > 0.0}
    prompt = f"Аналізуй мій портфель: {balances}. Що продавати і що купити сьогодні? Додай stop-loss."

    chat_response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )

    return chat_response.choices[0].message.content.strip()

# --- Збереження звіту в файл ---
def save_report(text):
    with open("daily_report.txt", "w") as f:
        f.write(text)

# --- Надсилання в Telegram ---
def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": ADMIN_CHAT_ID,
        "text": message
    }
    requests.post(url, data=data)

# --- Запуск ---
if __name__ == "__main__":
    try:
        report = generate_report()
        print(report)
        save_report(report)
        send_to_telegram(report)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        send_to_telegram(f"❌ GPT-Звіт не згенеровано: {e}")
