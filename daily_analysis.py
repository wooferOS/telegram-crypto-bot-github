import os
import json
import requests
import datetime
from dotenv import load_dotenv
from binance.client import Client
from openai import OpenAI

# Завантаження змінних з .env
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Клієнти
client = OpenAI(api_key=OPENAI_API_KEY)
binance = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
def get_wallet_balances():
    raw_balances = binance.get_account()["balances"]
    wallet = {}
    for b in raw_balances:
        asset = b["asset"]
        amount = float(b["free"])
        if amount > 0:
            wallet[asset] = amount
    return wallet

def get_usdt_to_uah():
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTUAH").json()
        return float(res["price"])
    except:
        return 39.5  # резервний курс

def get_avg_price(symbol):
    try:
        res = binance.get_avg_price(symbol=symbol)
        return float(res["price"])
    except:
        return 0.0
def build_detailed_wallet_report(wallet):
    report = []
    usdt_to_uah = get_usdt_to_uah()

    for asset, amount in wallet.items():
        if asset == "USDT":
            value = amount
            uah = value * usdt_to_uah
            report.append(f"*{asset}*: {amount:.4f} ≈ {uah:.2f}₴")
            continue

        pair = f"{asset}USDT"
        avg_price = get_avg_price(pair)
        total_usdt = avg_price * amount
        total_uah = total_usdt * usdt_to_uah
        report.append(
            f"*{asset}*: {amount} × {avg_price:.6f} = {total_usdt:.2f} USDT ≈ {total_uah:.2f}₴"
        )
    return "\n".join(report)
def generate_gpt_report(wallet_text):
    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    prompt = f"""
Ти — криптоасистент. Проаналізуй портфель користувача. Не використовуй знак $.
Дай рекомендації: які монети продавати, які купити, з поясненням, стоп-лоссами та прибутками. Використовуй лише USDT та гривні (₴).
    
Баланс користувача:
{wallet_text}

Ринок: Binance (https://www.binance.com/uk-UA/markets/overview)
Дата: {today}

Формат:
📊 Звіт на {today}
🔻 ПРОДАЖ: ...  
🔼 КУПІВЛЯ: ...  
📈 ОЧІКУВАНИЙ ПРИБУТОК: ...  
🧠 Прогноз: ...
"""

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Ти криптоаналітик. Формуй чіткий теханаліз зі знанням Binance Academy."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content.strip()


def save_report(text):
    now = datetime.datetime.now()
    folder = f"reports/{now.strftime('%Y-%m-%d')}"
    os.makedirs(folder, exist_ok=True)
    path = f"{folder}/daily_report_{now.strftime('%H-%M')}.md"
    with open(path, "w") as f:
        f.write(text)
    return path
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("❌ Telegram error:", e)

def main():
    wallet = get_wallet_balances()
    wallet_text = build_detailed_wallet_report(wallet)
    gpt_text = generate_gpt_report(wallet_text)

    full_report = f"📊 *Звіт крипто-портфелю*\n\n💰 *Баланс:*\n{wallet_text}\n\n📈 *GPT-звіт:*\n{gpt_text}"
    file_path = save_report(full_report)
    send_telegram(full_report)
    print(f"✅ Звіт надіслано. Збережено у {file_path}")

if __name__ == "__main__":
    main()
