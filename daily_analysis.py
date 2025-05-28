import os
from datetime import datetime
from dotenv import load_dotenv
from binance.client import Client
from openai import OpenAI

load_dotenv()

client = Client(os.environ["BINANCE_API_KEY"], os.environ["BINANCE_SECRET_KEY"])
openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def get_binance_balances():
    balances = client.get_account()["balances"]
    wallet = {}
    for b in balances:
        asset = b["asset"]
        free = float(b["free"])
        if free > 0 and asset not in ["USDT", "BUSD", "TUSD"]:
            wallet[asset] = free
    return wallet

def get_prices():
    tickers = client.get_all_tickers()
    return {t['symbol']: float(t['price']) for t in tickers}

def generate_wallet_report():
    balances = get_binance_balances()
    prices = get_prices()
    lines = []
    total_usdt = 0

    for asset, amount in balances.items():
        symbol = f"{asset}USDT"
        price = prices.get(symbol)
        if price:
            value = round(amount * price, 2)
            total_usdt += value
            lines.append(f"• {asset}: {amount} ≈ {value} USDT")

    lines.append(f"\n💰 Загальна вартість портфеля: {round(total_usdt, 2)} USDT")
    return "\n".join(lines), total_usdt

def generate_gpt_report(wallet_report):
    messages = [
        {"role": "system", "content": "Ти криптоаналітик. Дай короткий звіт на основі портфеля: що продати, що купити, які ризики."},
        {"role": "user", "content": f"Ось портфель користувача:\n{wallet_report}\n\nДай поради для короткострокового трейду з рівнями стоп-лосу і тейк-профіту."}
    ]
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=messages
    )
    return response.choices[0].message.content.strip()

def save_report(content):
    filename = f"daily_report_{datetime.now().strftime('%Y-%m-%d')}.md"
    with open(filename, "w") as f:
        f.write(content)
    print(f"✅ Звіт збережено у {filename}")

def main():
    print("📊 Генеруємо щоденний звіт...")
    wallet_report, total_usdt = generate_wallet_report()
    try:
        gpt_summary = generate_gpt_report(wallet_report)
    except Exception as e:
        gpt_summary = f"❌ Помилка GPT: {e}"

    final_report = (
        f"# 📈 Щоденний звіт ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
        f"💰 Баланс: {round(total_usdt, 2)} USDT\n\n"
        f"## 📊 Деталі портфеля:\n{wallet_report}\n\n"
        f"## 📈 GPT-аналітика:\n{gpt_summary}\n\n"
        f"👉 Для підтвердження дій:\n/confirm_buy або /confirm_sell"
    )

    save_report(final_report)

if __name__ == "__main__":
    main()
