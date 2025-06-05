import os
import time
import hmac
import hashlib
import requests
import decimal
from typing import Dict, List, Optional

from dotenv import load_dotenv
from binance.client import Client

# 🔐 Завантаження змінних середовища
load_dotenv(dotenv_path=os.path.expanduser("~/.env"))

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "PLACEHOLDER")
if BINANCE_API_KEY == "PLACEHOLDER":
    print("⚠️ Warning: BINANCE_API_KEY is empty. Make sure .env is loaded on server.")

BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "PLACEHOLDER")
if BINANCE_SECRET_KEY == "PLACEHOLDER":
    print(
        "⚠️ Warning: BINANCE_SECRET_KEY is empty. Make sure .env is loaded on server."
    )
BINANCE_BASE_URL = "https://api.binance.com"

# 🧩 Ініціалізація клієнта Binance
# ping=False запобігає зверненню до API під час ініціалізації, що
# важливо для середовищ без інтернет-доступу
client = Client(
    api_key=BINANCE_API_KEY,
    api_secret=BINANCE_SECRET_KEY,
    ping=False,
)
# 🕒 Отримання поточного timestamp для підпису запитів
def get_timestamp() -> int:
    return int(time.time() * 1000)

# 🔏 Підпис запиту для приватних endpoint'ів Binance
def sign_request(params: Dict[str, str]) -> Dict[str, str]:
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    params["signature"] = signature
    return params

# 📬 Заголовки для API-запитів
def get_headers() -> Dict[str, str]:
    return {
        "X-MBX-APIKEY": BINANCE_API_KEY
    }
# 👤 Отримання повної інформації про акаунт
def get_account_info() -> Optional[Dict]:
    url = f"{BINANCE_BASE_URL}/api/v3/account"
    params = {"timestamp": get_timestamp()}
    signed_params = sign_request(params)
    try:
        response = requests.get(url, headers=get_headers(), params=signed_params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"[Binance] ❌ Помилка при отриманні акаунта: {e}")
        return None
# 💰 Отримання балансу користувача
def get_balances() -> Dict[str, float]:
    """
    Повертає словник {asset: amount}, фільтруючи лише активи з ненульовим балансом.
    """
    try:
        account = client.get_account()
        balances = {}
        for balance in account.get("balances", []):
            asset = balance.get("asset")
            free = float(balance.get("free", 0))
            locked = float(balance.get("locked", 0))
            total = free + locked
            if total > 0:
                balances[asset] = total
        return balances
    except Exception as e:
        print(f"[Binance] ❌ Помилка при отриманні балансу: {e}")
        return {}
# 💹 Отримання цін усіх монет до USDT
def get_prices() -> Dict[str, float]:
    """
    Повертає словник {asset: price_in_usdt} для всіх пар, що завершуються на USDT.
    """
    try:
        tickers = client.get_all_tickers()
        prices = {}
        for ticker in tickers:
            symbol = ticker.get("symbol", "")
            if symbol.endswith("USDT"):
                asset = symbol.replace("USDT", "")
                price = float(ticker.get("price", 0))
                prices[asset] = price
        return prices
    except Exception as e:
        print(f"[Binance] ❌ Помилка при отриманні цін: {e}")
        return {}
# 🧾 Формування поточного портфеля в USDT
def get_current_portfolio() -> Dict[str, float]:
    """
    Повертає словник {symbol: value_in_usdt} лише для монет з ненульовим балансом.
    """
    balances = get_balances()
    prices = get_prices()
    portfolio = {}

    for asset, amount in balances.items():
        if asset == "USDT":
            portfolio[asset] = round(amount, 4)
        elif asset in prices:
            portfolio[asset] = round(amount * prices[asset], 4)
        else:
            print(f"[Binance] ⚠️ Немає ціни для {asset}, пропускаємо.")

    return portfolio
# 📈 Отримання поточної ціни активу
def get_coin_price(symbol: str) -> Optional[float]:
    """
    Повертає поточну ціну монети в USDT, наприклад: get_coin_price("BTC") → 68300.0
    """
    try:
        url = f"{BINANCE_BASE_URL}/api/v3/ticker/price"
        response = requests.get(url, params={"symbol": f"{symbol}USDT"})
        response.raise_for_status()
        return float(response.json()["price"])
    except Exception as e:
        print(f"[Binance] ❌ Помилка при отриманні ціни {symbol}USDT: {e}")
        return None
# 🔢 Отримання точності символу
def get_symbol_precision(symbol: str) -> int:
    """
    Повертає кількість десяткових знаків (precision) для символу.
    Наприклад: BTCUSDT → 6
    """
    try:
        url = f"{BINANCE_BASE_URL}/api/v3/exchangeInfo"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step_size = float(f["stepSize"])
                        return abs(decimal.Decimal(str(step_size)).as_tuple().exponent)
    except Exception as e:
        print(f"[Binance] ⚠️ Помилка при отриманні точності для {symbol}: {e}")
    
    return 2  # 🔁 Значення за замовчуванням

def get_full_asset_info():
    # ⚠️ Заміни нижче на справжній код
    return {
        "balances": [
            {"symbol": "ADA", "amount": 15.3, "usdt_value": 10.25, "uah_value": 415.77},
            {"symbol": "XRP", "amount": 9.99, "usdt_value": 21.35, "uah_value": 865.32},
        ],
        "pnl": [
            {"symbol": "ADA", "prev_amount": 15.3, "current_amount": 15.3, "diff": 0.0, "percent": 0.0},
            {"symbol": "XRP", "prev_amount": 10.0, "current_amount": 9.99, "diff": -0.01, "percent": -0.1},
        ],
        "recommend_sell": [
            {"symbol": "ADA", "change_percent": -5.32},
            {"symbol": "PEPE", "change_percent": -10.1}
        ],
        "recommend_buy": [
            {"symbol": "LPTUSDT", "volume": 123456.0, "change_percent": 12.3},
            {"symbol": "TRBUSDT", "volume": 98765.0, "change_percent": 18.4}
        ],
        "expected_profit": 14.77,
        "expected_profit_block": "- Продаж ADA: + 7.2\n- Купівля TRX: + 2.3\n= Разом: + 9.5 (≈ +15%)",
        "gpt_forecast": "ADA виглядає сильно, PEPE втрачає позиції.",
    }

# 📉 Отримання останньої ціни через ручний endpoint
def get_last_price(symbol: str) -> float:
    """
    Повертає останню відому ціну символу типу BTCUSDT.
    """
    try:
        url = f"{BINANCE_BASE_URL}/api/v3/ticker/price?symbol={symbol}"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return float(data["price"])
    except Exception as e:
        print(f"[Binance] ⚠️ Помилка при отриманні останньої ціни {symbol}: {e}")
        return 0.0
# 📋 Приклад функції: перевірка, чи актив підтримується ботом
def is_asset_supported(symbol: str, whitelist: Optional[List[str]] = None) -> bool:
    """
    Перевіряє, чи символ підтримується згідно з whitelist.
    """
    if whitelist is None:
        whitelist = [
            "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT",
            "TRX", "LINK", "MATIC", "LTC", "BCH", "ATOM", "NEAR", "FIL",
            "ICP", "ETC", "HBAR", "VET", "RUNE", "INJ", "OP", "ARB", "SUI",
            "STX", "TIA", "SEI", "1000PEPE"
        ]
    return symbol.upper() in whitelist
# 🧪 Перевірка роботи модуля
if __name__ == "__main__":
    print("🔧 Binance API модуль запущено напряму.")
    print("➡️ Поточний портфель:")
    portfolio = get_current_portfolio()
    for asset, value in portfolio.items():
        print(f"• {asset}: ${value:.2f}")
