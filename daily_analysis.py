import os
import datetime
import json
import requests
from openai import OpenAI
from binance.client import Client
from dotenv import load_dotenv

# Завантажуємо змінні з .env
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Ініціалізація клієнтів
openai_client = OpenAI(api_key=OPENAI_API_KEY)
binance_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

def get_binance_balances():
    balances = binance_client.get_account()["balances"]
    wallet = {}
    for b in balances:
        asset = b["asset"]
        free = float(b["free"])
        if free > 0:
            wallet[asset] = free
    return wallet

def generate_wallet_report(wallet):
    lines = [f"{asset}: {amount}" for asset, amount in wallet.items()]
    return "\n".join(lines)
def calculate_profit_percentage(today_wallet, yesterday_wallet):
    changes = []
    for asset, amount in today_wallet.items():
        y_amount = yesterday_wallet.get(asset, 0)
        if y_amount > 0:
            change = ((amount - y_amount) / y_amount) * 100
            changes.append(f"{asset}: {change:.2f}%")
    return "\n".join(changes) if changes else "📉 Недостатньо даних для порівняння."

def generate_gpt_report(wallet_report):
    prompt = f"""
Ти — досвідчений трейдер. Проаналізуй цей портфель криптовалют, сформуй короткий технічний звіт:

{wallet_report}

1. Що можна продати?
2. Що доцільно докупити сьогодні?
3. Які стоп-лоси виставити?
4. Який прогноз прибутку на 24 год?

Не надавай фінансових порад, лише технічну думку.
"""

    completion = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Ти GPT-аналітик ринку криптовалют."},
            {"role": "user", "content": prompt}
        ]
    )
    return completion.choices[0].message.content.strip()

def save_report_to_file(text, folder="reports"):
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M")
    folder_path = os.path.join(folder, date_str)
    os.makedirs(folder_path, exist_ok=True)
    file_path = os.path.join(folder_path, f"daily_report_{time_str}.md")
    with open(file_path, "w") as f:
        f.write(text)
    return file_path
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Помилка надсилання в Telegram: {e}")

def log_event(text, logfile="daily.log"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {text}\n"
    with open(logfile, "a") as f:
        f.write(line)

def main():
    log_event("🔁 Початок щоденного аналізу...")
    today_wallet = get_binance_balances()
    wallet_report = generate_wallet_report(today_wallet)

    gpt_text = generate_gpt_report(wallet_report)

    full_report = f"""📊 *Звіт крипто-портфелю*

💰 *Баланс:*
{wallet_report}

📈 *GPT-звіт:*
{gpt_text}
"""
    file_path = save_report_to_file(full_report)
    send_telegram_message(full_report)
    log_event("✅ Звіт сформовано та надіслано.")
def save_report_to_file(text):
    today = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    folder = "reports"
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"daily_report_{today}.md")
    with open(path, "w") as f:
        f.write(text)
    return path

if __name__ == "__main__":
    main()
