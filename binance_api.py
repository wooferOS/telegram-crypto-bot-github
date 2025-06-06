import os
import time
import hmac
import hashlib
import logging
import requests
import decimal
from typing import Dict, List, Optional
import asyncio

from dotenv import load_dotenv
from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET


def safe_close_client(client: Client) -> None:
    """Safely close Binance client HTTP session."""
    try:
        if hasattr(client, "session") and client.session:
            client.session.close()
    except Exception:
        pass


class SafeBinanceClient(Client):
    """Binance Client with safe session cleanup on deletion."""

    def __del__(self) -> None:
        safe_close_client(self)

# 🔐 Завантаження змінних середовища
load_dotenv(dotenv_path=os.path.expanduser("~/.env"))

TELEGRAM_LOG_PREFIX = "\ud83d\udce1 [BINANCE]"
logger = logging.getLogger(__name__)

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
    logger.warning("⚠️ Binance API credentials are missing.")
BINANCE_BASE_URL = "https://api.binance.com"

# 🧩 Ініціалізація клієнта Binance без обов'язкового ping
try:
    client = SafeBinanceClient(
        api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY, ping=False
    )
except TypeError:
    client = SafeBinanceClient(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
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
        logger.error(f"{TELEGRAM_LOG_PREFIX} Помилка при отриманні акаунта: {e}")
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
        logger.error(f"{TELEGRAM_LOG_PREFIX} Помилка при отриманні балансу: {e}")
        return {}


async def get_binance_balances() -> Dict[str, Dict[str, float]]:
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_SECRET_KEY")
    client = Client(api_key, api_secret)

    try:
        account = client.get_account()
        prices = client.get_all_tickers()
        price_map = {p["symbol"]: float(p["price"]) for p in prices}

        balances = {}
        for b in account["balances"]:
            asset = b["asset"]
            free = float(b["free"])
            if free > 0:
                symbol = asset + "USDT"
                usdt_value = free * price_map.get(symbol, 0)
                balances[asset] = {"free": free, "usdtValue": round(usdt_value, 2)}
        return balances
    finally:
        try:
            if hasattr(client, "session") and client.session:
                client.session.close()
        except Exception:
            pass
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
        logger.error(f"{TELEGRAM_LOG_PREFIX} Помилка при отриманні цін: {e}")
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
            logger.warning(f"{TELEGRAM_LOG_PREFIX} Немає ціни для {asset}, пропускаємо.")

    return portfolio

# --- Допоміжні функції для простішої інтеграції з Telegram-ботом ---

def get_usdt_balance() -> float:
    """Повертає доступний баланс USDT."""
    try:
        balances = client.get_asset_balance(asset="USDT")
        return float(balances.get("free", 0.0))
    except Exception as e:
        logger.error(f"{TELEGRAM_LOG_PREFIX} Помилка отримання балансу USDT: {e}")
        return 0.0


def get_token_balance(symbol: str) -> float:
    """Повертає баланс конкретного токена."""
    try:
        balances = client.get_asset_balance(asset=symbol.upper())
        return float(balances.get("free", 0.0))
    except Exception as e:
        logger.error(f"{TELEGRAM_LOG_PREFIX} Баланс {symbol.upper()} недоступний: {e}")
        return 0.0


def get_symbol_price(symbol: str) -> float:
    """Поточна ціна токена до USDT."""
    try:
        ticker = client.get_symbol_ticker(symbol=f"{symbol.upper()}USDT")
        return float(ticker.get("price", 0.0))
    except Exception as e:
        logger.error(f"{TELEGRAM_LOG_PREFIX} Помилка ціни для {symbol}: {e}")
        return 0.0


def place_market_order(symbol: str, side: str, quantity: float):
    """Виконує маркет-ордер купівлі або продажу."""
    try:
        order = client.create_order(
            symbol=f"{symbol.upper()}USDT",
            side=SIDE_BUY if side == "BUY" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
        )
        logger.info(f"{TELEGRAM_LOG_PREFIX} Ордер виконано: {order}")
        return order
    except Exception as e:
        logger.error(f"{TELEGRAM_LOG_PREFIX} Помилка створення ордера: {e}")
        return None


def get_usdt_to_uah_rate() -> float:
    """Повертає курс USDT до гривні."""
    try:
        ticker = client.get_symbol_ticker(symbol="USDTUAH")
        return float(ticker.get("price", 39.2))
    except Exception as e:
        logger.warning(f"{TELEGRAM_LOG_PREFIX} Помилка отримання курсу UAH: {e}")
        return 39.2


def get_token_value_in_uah(symbol: str) -> float:
    """Вартість токена у гривнях."""
    price_usdt = get_symbol_price(symbol)
    uah_rate = get_usdt_to_uah_rate()
    return round(price_usdt * uah_rate, 2)


def notify_telegram(message: str) -> None:
    """Надсилає повідомлення адміну у Telegram, якщо токен та chat_id вказані."""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID", os.getenv("CHAT_ID", ""))
    if not token or not chat_id:
        logger.debug(f"{TELEGRAM_LOG_PREFIX} Telegram credentials not set")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
    except Exception as e:
        logger.warning(f"{TELEGRAM_LOG_PREFIX} Не вдалося надіслати повідомлення у Telegram: {e}")
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
        logger.error(f"{TELEGRAM_LOG_PREFIX} Помилка при отриманні ціни {symbol}USDT: {e}")
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
        logger.warning(f"{TELEGRAM_LOG_PREFIX} Помилка при отриманні точності для {symbol}: {e}")
    
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
        logger.warning(f"{TELEGRAM_LOG_PREFIX} Помилка при отриманні останньої ціни {symbol}: {e}")
        return 0.0

# 📊 Отримання цін за останні 24 години
def get_price_history_24h(symbol: str) -> Optional[List[float]]:
    """Return list of hourly close prices for the last 24 hours."""
    try:
        url = f"{BINANCE_BASE_URL}/api/v3/klines"
        params = {"symbol": f"{symbol.upper()}USDT", "interval": "1h", "limit": 24}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        return [float(item[4]) for item in data]
    except Exception as e:
        logger.warning(
            f"{TELEGRAM_LOG_PREFIX} Помилка при отриманні історії цін {symbol}: {e}"
        )
        return None


def get_recent_trades(symbol: str = "BTCUSDT", limit: int = 5) -> List[Dict]:
    """Return recent trades from Binance."""
    try:
        return client.get_my_trades(symbol=symbol, limit=limit)
    except Exception as e:
        logger.warning(
            f"{TELEGRAM_LOG_PREFIX} Помилка при отриманні історії угод: {e}"
        )
        return []


def get_portfolio_stats() -> Dict[str, float]:
    """Return total portfolio value in USDT and UAH."""
    portfolio = get_current_portfolio()
    total_usdt = sum(portfolio.values())
    total_uah = round(total_usdt * get_usdt_to_uah_rate(), 2)
    return {"total_usdt": round(total_usdt, 4), "total_uah": total_uah}
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
    logger.info("🔧 Binance API модуль запущено напряму.")
    logger.info("➡️ Поточний портфель:")
    portfolio = get_current_portfolio()
    for asset, value in portfolio.items():
        logger.info(f"• {asset}: ${value:.2f}")
