import json
import os
from binance_api import get_binance_balances, get_token_price, sell_token

BALANCE_FILE = "last_total_balance.json"
MIN_DROP = 0.01  # якщо падає хоча б на 0.01 — тригер

IGNORED_TOKENS = {"AMB"}  # делістинговані токени

def get_total_estimated_balance():
    balances = get_binance_balances()
    total = 0.0
    for symbol, amount in balances.items():
        if symbol in IGNORED_TOKENS or amount == 0:
            continue
        price = get_token_price(symbol)
        total += amount * price
    return round(total, 4)

def load_last_balance():
    if os.path.exists(BALANCE_FILE):
        return json.load(open(BALANCE_FILE)).get("last_balance", 0.0)
    return 0.0

def save_last_balance(balance):
    json.dump({"last_balance": balance}, open(BALANCE_FILE, "w"))

def panic_sell():
    balances = get_binance_balances()
    for symbol, amount in balances.items():
        if symbol not in IGNORED_TOKENS and amount > 0:
            sell_token(symbol)

def main():
    current = get_total_estimated_balance()
    last = load_last_balance()

    if last == 0.0:
        save_last_balance(current)
        return

    if current + MIN_DROP < last:
        print(f"⚠️ Баланс впав: було {last}, стало {current}")
        panic_sell()
    else:
        print(f"✅ Баланс стабільний: {current}")

    save_last_balance(current)

if __name__ == "__main__":
    main()
