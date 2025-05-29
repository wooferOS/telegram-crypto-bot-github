import os
import datetime
import requests
from openai import OpenAI
from binance.client import Client

# Змінні середовища
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
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content

def send_telegram_text(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def send_telegram_file(filepath, caption="📎 Щоденний звіт"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    with open(filepath, "rb") as file:
        files = {"document": file}
        data = {"chat_id": ADMIN_CHAT_ID, "caption": caption}
        requests.post(url, data=data, files=files)

def load_yesterday_wallet(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return {line.split(":")[0].strip(): float(line.split(":")[1]) for line in lines}
    return {}

def save_today_wallet(wallet, filepath):
    with open(filepath, "w", encoding="utf-8") as f:
        for asset, amount in wallet.items():
            f.write(f"{asset}: {amount}\n")

def log_message(message):
    with open("daily.log", "a", encoding="utf-8") as log:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.write(f"[{timestamp}] {message}\n")

def main():
    now = datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%d.%m.%Y %H:%M")
    reports_dir = f"reports/{today}"
    os.makedirs(reports_dir, exist_ok=True)
    wallet_file = f"{reports_dir}/wallet.txt"

    log_message("🔁 Початок щоденного аналізу...")

    wallet = get_binance_balances()
    wallet_report = generate_wallet_report(wallet)

    yesterday_file = f"reports/{(now - datetime.timedelta(days=1)).strftime('%Y-%m-%d')}/wallet.txt"
    yesterday_wallet = load_yesterday_wallet(yesterday_file)
    profit_change = calculate_profit_percentage(wallet, yesterday_wallet)

    try:
        gpt_summary = generate_gpt_report(wallet_report)
    except Exception as e:
        gpt_summary = f"❌ Помилка GPT: {str(e)}"
        log_message(gpt_summary)

    markdown = f"""# 📊 Щоденний звіт ({timestamp})

## 💼 Поточний баланс Binance:
{wallet_report}

## 📊 Зміна порівняно з учора:
{profit_change}

## 📈 GPT-аналітика:
{gpt_summary}
"""

    report_path = f"{reports_dir}/daily_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    save_today_wallet(wallet, wallet_file)

    send_telegram_text(f"✅ Щоденний звіт за {timestamp}")
    send_telegram_file(report_path)

    log_message("✅ Звіт сформовано та надіслано.\n")

if __name__ == "__main__":
    main()
