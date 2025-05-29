from datetime import datetime
import os
import json
import requests
from binance.client import Client
from openai import OpenAI
from dotenv import load_dotenv
from utils import convert_to_uah, get_price_usdt
from pnl import get_daily_pnl

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

def calculate_daily_pnl(current_wallet, snapshot_file="wallet_snapshot.json"):
    previous = {}
    if os.path.exists(snapshot_file):
        with open(snapshot_file, "r") as f:
            previous = json.load(f)

    pnl_lines = []
    for asset, current_amount in current_wallet.items():
        prev_amount = previous.get(asset, 0)
        if prev_amount == 0:
            continue
        delta = current_amount - prev_amount
        percent = (delta / prev_amount) * 100
        pnl_lines.append(f"{asset}: {prev_amount:.4f} → {current_amount:.4f} ({delta:+.4f}, {percent:+.2f}%)")

    with open(snapshot_file, "w") as f:
        json.dump(current_wallet, f)

    return "\n".join(pnl_lines) if pnl_lines else "Немає змін у PNL"
    
def save_trade_history(history, filename='trade_history.json'):
    import json
    with open(filename, 'w') as f:
        json.dump(history, f, indent=2)

def generate_gpt_report(wallet_text):
    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    prompt = f"""
Ти — криптоаналітик. Проаналізуй портфель користувача. Використовуй **тільки** USDT та гривні (₴), без символу $.

**Формуй чіткий прогноз на базі Binance Markets**:
https://www.binance.com/uk-UA/markets/overview

Вивід має містити:

1. 🔻 ПРОДАЖ:
   - <монета> — <кількість> ≈ <вартість в USDT> ≈ <вартість в ₴>
   - Причина: коротка, лаконічна.
   - Команда: /confirmsell<монета>

2. 🔼 КУПІВЛЯ:
   - <монета> — <кількість або обʼєм> ≈ <вартість в USDT> ≈ <вартість в ₴>
   - Стоп-лосс: -X%, Тейк-профіт: +Y%
   - Команда: /confirmbuy<монета>

3. 📈 ОЧІКУВАНИЙ ПРИБУТОК:
   - Сума в USDT і ₴.

4. 🧠 Прогноз: чітка оцінка ситуації. Не вживати "можливо", "я думаю", "ймовірно". Ти асистент і формуєш рішення.

---

Баланс користувача:
{wallet_text}

Дата: {today}
"""

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Ти GPT-аналітик. Формуй звіт по крипто-портфелю з Binance з урахуванням поточних даних. Уникай $ — лише USDT та ₴. Використовуй досвід Binance Academy для прогнозу."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content.strip()

def save_wallet_snapshot(wallet):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    os.makedirs("wallet_snapshots", exist_ok=True)
    with open(f"wallet_snapshots/{today}.json", "w") as f:
        json.dump(wallet, f, indent=2)

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
    daily_pnl = calculate_daily_pnl(wallet)
    gpt_text = generate_gpt_report(wallet_text)

    full_report = f"📊 *Звіт крипто-портфелю*\n\n💰 *Баланс:*\n{wallet_text}\n\n📉 *Щоденний PNL:*\n{daily_pnl}\n\n📈 *GPT-звіт:*\n{gpt_text}"
    file_path = save_report(full_report)
    send_telegram(full_report)
    save_wallet_snapshot(wallet)
    print(f"✅ Звіт надіслано. Збережено у {file_path}")

if __name__ == "__main__":
    main()

    
