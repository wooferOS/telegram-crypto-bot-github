import os
import time
import hmac
import hashlib
import requests
from typing import Dict, List, Tuple

from dotenv import load_dotenv

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
BINANCE_BASE_URL = "https://api.binance.com"

HEADERS = {
    "X-MBX-APIKEY": BINANCE_API_KEY
}
def get_timestamp() -> int:
    return int(time.time() * 1000)


def sign_request(params: Dict[str, str]) -> Dict[str, str]:
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    params["signature"] = signature
    return params
def get_headers() -> Dict[str, str]:
    return {
        "X-MBX-APIKEY": BINANCE_API_KEY
    }


def get_account_info() -> Optional[Dict]:
    url = f"{BINANCE_BASE_URL}/api/v3/account"
    params = {"timestamp": get_timestamp()}
    signed_params = sign_request(params)
    try:
        response = requests.get(url, headers=get_headers(), params=signed_params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"[Binance] ❌ Error getting account info: {e}")
        return None
def get_prices() -> Dict[str, float]:
    """
    Отримує актуальні ціни всіх пар до USDT.
    """
    url = f"{BINANCE_BASE_URL}/api/v3/ticker/price"
    try:
        response = requests.get(url)
        response.raise_for_status()
        prices_raw = response.json()
        prices = {
            item["symbol"]: float(item["price"])
            for item in prices_raw if item["symbol"].endswith("USDT")
        }
        return prices
    except Exception as e:
        print(f"[Binance] ❌ Error fetching prices: {e}")
        return {}
def get_balances() -> Dict[str, float]:
    """
    Отримує баланс по всіх монетах користувача.
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
        print(f"[Binance] ❌ Error fetching balances: {e}")
        return {}
def get_prices() -> Dict[str, float]:
    """
    Отримує актуальні ціни всіх пар до USDT.
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
        print(f"[Binance] ❌ Error fetching prices: {e}")
        return {}
def get_current_portfolio() -> Dict[str, float]:
    """
    Повертає словник {symbol: value_in_usdt} лише для монет з ненульовим балансом.
    """
    balances = get_balances()
    prices = get_prices()
    portfolio = {}

    for asset, amount in balances.items():
        if asset == "USDT":
            portfolio[asset] = amount
        elif asset in prices:
            portfolio[asset] = round(amount * prices[asset], 4)
        else:
            print(f"[Binance] ⚠️ Немає ціни для {asset}, пропускаємо.")

    return portfolio
def get_coin_price(symbol: str) -> Optional[float]:
    """
    Повертає поточну ціну монети в USDT.
    """
    url = f"{BINANCE_API_URL}/api/v3/ticker/price"
    try:
        response = requests.get(url, params={"symbol": f"{symbol}USDT"})
        response.raise_for_status()
        return float(response.json()["price"])
    except Exception as e:
        print(f"[Binance] ❌ Помилка при отриманні ціни {symbol}USDT:", e)
        return None
def get_symbol_precision(symbol: str) -> int:
    """
    Повертає точність кількості монет для символу (кількість десяткових знаків).
    """
    try:
        exchange_info = requests.get(f"{BINANCE_API_URL}/api/v3/exchangeInfo").json()
        for s in exchange_info.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step_size = float(f["stepSize"])
                        return abs(decimal.Decimal(str(step_size)).as_tuple().exponent)
    except Exception as e:
        print(f"[Binance] ⚠️ Помилка при отриманні точності символу {symbol}: {e}")
    return 2  # дефолт
def get_last_price(symbol: str) -> float:
    """
    Отримує останню ціну для вказаного торгового символу з Binance.
    """
    try:
        url = f"{BINANCE_API_URL}/api/v3/ticker/price?symbol={symbol}"
        response = requests.get(url, timeout=5)
        data = response.json()
        return float(data["price"])
    except Exception as e:
        print(f"[Binance] ⚠️ Помилка при отриманні ціни {symbol}: {e}")
        return 0.0
if __name__ == "__main__":
    print("Цей файл призначений для імпорту, а не для прямого запуску.")
