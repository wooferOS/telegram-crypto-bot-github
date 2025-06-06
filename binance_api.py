# pylint: disable=missing-docstring
"""Binance API helper module.

This module provides synchronous helpers for interacting with the Binance Spot
API and is designed for use in a Telegram bot.
"""

from __future__ import annotations

import os
import time
import hmac
import hashlib
import logging
import decimal
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET
from binance.exceptions import BinanceAPIException


logger = logging.getLogger(__name__)
TELEGRAM_LOG_PREFIX = "\ud83d\udce1 [BINANCE]"

# Load environment variables from ~/.env if present
load_dotenv(os.path.expanduser("~/.env"))

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
BINANCE_BASE_URL = "https://api.binance.com"

print(f"[DEBUG] API: {BINANCE_API_KEY[:6]}..., SECRET: {BINANCE_SECRET_KEY[:6]}...")


class SafeBinanceClient(Client):
    """Client that closes its HTTP session when garbage collected."""

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        safe_close_client(self)


def safe_close_client(client: Client) -> None:
    """Close client session if present."""

    try:
        if getattr(client, "session", None):
            client.session.close()
    except Exception:  # pragma: no cover - cleanup must not fail
        pass


# Initialise global Binance client
client = SafeBinanceClient(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)


# ---------------------------------------------------------------------------
# Low level helpers
# ---------------------------------------------------------------------------

def get_timestamp() -> int:
    """Return current timestamp in milliseconds for signed requests."""

    return int(time.time() * 1000)


def sign_request(params: Dict[str, str]) -> Dict[str, str]:
    """Add HMAC SHA256 signature to request parameters."""

    query = "&".join(f"{k}={v}" for k, v in params.items())
    signature = hmac.new(
        BINANCE_SECRET_KEY.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    params["signature"] = signature
    return params


def get_headers() -> Dict[str, str]:
    """Return HTTP headers with API key."""

    return {"X-MBX-APIKEY": BINANCE_API_KEY}


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

def get_account_info() -> Optional[Dict[str, object]]:
    """Return detailed account information using signed HTTP request."""

    url = f"{BINANCE_BASE_URL}/api/v3/account"
    params = sign_request({"timestamp": get_timestamp()})
    try:
        resp = requests.get(url, headers=get_headers(), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("%s Помилка при отриманні акаунта: %s", TELEGRAM_LOG_PREFIX, exc)
        return None


def get_balances() -> Dict[str, float]:
    """Return mapping of asset to total balance (free + locked)."""

    try:
        account = client.get_account()
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("%s Помилка при отриманні балансу: %s", TELEGRAM_LOG_PREFIX, exc)
        return {}

    balances: Dict[str, float] = {}
    for bal in account.get("balances", []):
        asset = bal.get("asset")
        free = float(bal.get("free", 0))
        locked = float(bal.get("locked", 0))
        total = free + locked
        if total > 0:
            balances[asset] = total
    return balances


def get_binance_balances() -> Dict[str, float]:
    """Return available balances with automatic API diagnostics."""

    try:
        temp_client = Client(
            os.getenv("BINANCE_API_KEY"),
            os.getenv("BINANCE_SECRET_KEY"),
            {"verify": True, "timeout": 20},
        )

        logging.debug(
            f"[DEBUG] API: {os.getenv('BINANCE_API_KEY')[:8]}..., SECRET: {os.getenv('BINANCE_SECRET_KEY')[:8]}..."
        )

        try:
            # Тестовий пінг до Binance
            temp_client.ping()
            logging.info("✅ Binance API доступний")

            account = temp_client.get_account()
            balances = {
                asset["asset"]: float(asset["free"])
                for asset in account["balances"]
                if float(asset["free"]) > 0
            }
            return balances

        except BinanceAPIException as e:
            logging.error(f"📛 [BINANCE] Помилка при отриманні балансу: {e}")
            if e.code == -2015:
                logging.error(
                    "❌ Можливо: (1) ключ недійсний, (2) немає прав, (3) IP не в whitelist."
                )
            raise e

    except Exception as ex:  # pragma: no cover - diagnostics must not fail
        logging.exception("❗ Невідома помилка при ініціалізації Binance клієнта")
        return {}


def get_prices() -> Dict[str, float]:
    """Return mapping of asset to its price in USDT."""

    try:
        tickers = client.get_all_tickers()
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("%s Помилка при отриманні цін: %s", TELEGRAM_LOG_PREFIX, exc)
        return {}

    prices: Dict[str, float] = {}
    for t in tickers:
        symbol = t.get("symbol", "")
        if symbol.endswith("USDT"):
            asset = symbol.replace("USDT", "")
            prices[asset] = float(t.get("price", 0))
    return prices


def get_current_portfolio() -> Dict[str, float]:
    """Return portfolio with values in USDT for non-zero balances."""

    balances = get_balances()
    prices = get_prices()
    portfolio: Dict[str, float] = {}

    for asset, amount in balances.items():
        if asset == "USDT":
            portfolio[asset] = round(amount, 4)
        elif asset in prices:
            portfolio[asset] = round(amount * prices[asset], 4)
        else:
            logger.warning("%s Немає ціни для %s, пропускаємо.", TELEGRAM_LOG_PREFIX, asset)

    return portfolio


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def get_usdt_balance() -> float:
    """Return available USDT balance."""

    try:
        bal = client.get_asset_balance(asset="USDT")
        return float(bal.get("free", 0))
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("%s Помилка отримання балансу USDT: %s", TELEGRAM_LOG_PREFIX, exc)
        return 0.0


def get_token_balance(symbol: str) -> float:
    """Return available balance of specific token."""

    try:
        bal = client.get_asset_balance(asset=symbol.upper())
        return float(bal.get("free", 0))
    except Exception as exc:
        logger.error(
            "%s Баланс %s недоступний: %s", TELEGRAM_LOG_PREFIX, symbol.upper(), exc
        )
        return 0.0


def get_symbol_price(symbol: str) -> float:
    """Return current price of token to USDT."""

    try:
        ticker = client.get_symbol_ticker(symbol=f"{symbol.upper()}USDT")
        return float(ticker.get("price", 0))
    except Exception as exc:
        logger.error("%s Помилка ціни для %s: %s", TELEGRAM_LOG_PREFIX, symbol, exc)
        return 0.0


def place_market_order(symbol: str, side: str, quantity: float) -> Optional[Dict[str, object]]:
    """Execute a market order to buy or sell."""

    try:
        order = client.create_order(
            symbol=f"{symbol.upper()}USDT",
            side=SIDE_BUY if side.upper() == "BUY" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
        )
        logger.info("%s Ордер виконано: %s", TELEGRAM_LOG_PREFIX, order)
        return order
    except Exception as exc:
        logger.error("%s Помилка створення ордера: %s", TELEGRAM_LOG_PREFIX, exc)
        return None


def get_usdt_to_uah_rate() -> float:
    """Return USDT to UAH conversion rate."""

    try:
        ticker = client.get_symbol_ticker(symbol="USDTUAH")
        return float(ticker.get("price", 39.2))
    except Exception as exc:
        logger.warning(
            "%s Помилка отримання курсу UAH: %s", TELEGRAM_LOG_PREFIX, exc
        )
        return 39.2


def get_token_value_in_uah(symbol: str) -> float:
    """Return token price converted to UAH."""

    return round(get_symbol_price(symbol) * get_usdt_to_uah_rate(), 2)


def notify_telegram(message: str) -> None:
    """Send a notification to Telegram if credentials are configured."""

    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID", os.getenv("CHAT_ID", ""))
    if not token or not chat_id:
        logger.debug("%s Telegram credentials not set", TELEGRAM_LOG_PREFIX)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning(
            "%s Не вдалося надіслати повідомлення у Telegram: %s",
            TELEGRAM_LOG_PREFIX,
            exc,
        )


# ---------------------------------------------------------------------------
# Additional helpers
# ---------------------------------------------------------------------------

def get_coin_price(symbol: str) -> Optional[float]:
    """Return last known coin price using direct HTTP call."""

    url = f"{BINANCE_BASE_URL}/api/v3/ticker/price"
    try:
        resp = requests.get(url, params={"symbol": f"{symbol}USDT"}, timeout=5)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as exc:
        logger.error(
            "%s Помилка при отриманні ціни %sUSDT: %s", TELEGRAM_LOG_PREFIX, symbol, exc
        )
        return None


def get_symbol_precision(symbol: str) -> int:
    """Return precision for trading symbol (number of decimals)."""

    url = f"{BINANCE_BASE_URL}/api/v3/exchangeInfo"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        step = float(f.get("stepSize"))
                        return abs(decimal.Decimal(str(step)).as_tuple().exponent)
    except Exception as exc:
        logger.warning(
            "%s Помилка при отриманні точності для %s: %s",
            TELEGRAM_LOG_PREFIX,
            symbol,
            exc,
        )
    return 2


def get_full_asset_info() -> Dict[str, object]:
    """Placeholder for extended asset information."""

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
            {"symbol": "PEPE", "change_percent": -10.1},
        ],
        "recommend_buy": [
            {"symbol": "LPTUSDT", "volume": 123456.0, "change_percent": 12.3},
            {"symbol": "TRBUSDT", "volume": 98765.0, "change_percent": 18.4},
        ],
        "expected_profit": 14.77,
        "expected_profit_block": "- Продаж ADA: + 7.2\n- Купівля TRX: + 2.3\n= Разом: + 9.5 (≈ +15%)",
        "gpt_forecast": "ADA виглядає сильно, PEPE втрачає позиції.",
    }


def get_last_price(symbol: str) -> float:
    """Return last price for trading symbol using REST API."""

    url = f"{BINANCE_BASE_URL}/api/v3/ticker/price?symbol={symbol}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as exc:
        logger.warning(
            "%s Помилка при отриманні останньої ціни %s: %s",
            TELEGRAM_LOG_PREFIX,
            symbol,
            exc,
        )
        return 0.0


def get_price_history_24h(symbol: str) -> Optional[List[float]]:
    """Return list of hourly close prices for the last 24 hours."""

    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": f"{symbol.upper()}USDT", "interval": "1h", "limit": 24}
    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        return [float(item[4]) for item in resp.json()]
    except Exception as exc:
        logger.warning(
            "%s Помилка при отриманні історії цін %s: %s",
            TELEGRAM_LOG_PREFIX,
            symbol,
            exc,
        )
        return None


def get_recent_trades(symbol: str = "BTCUSDT", limit: int = 5) -> List[Dict[str, object]]:
    """Return recent trades from Binance."""

    try:
        return client.get_my_trades(symbol=symbol, limit=limit)
    except Exception as exc:
        logger.warning(
            "%s Помилка при отриманні історії угод: %s", TELEGRAM_LOG_PREFIX, exc
        )
        return []


def get_portfolio_stats() -> Dict[str, float]:
    """Return total portfolio value both in USDT and UAH."""

    portfolio = get_current_portfolio()
    total_usdt = sum(portfolio.values())
    total_uah = round(total_usdt * get_usdt_to_uah_rate(), 2)
    return {"total_usdt": round(total_usdt, 4), "total_uah": total_uah}


def is_asset_supported(symbol: str, whitelist: Optional[List[str]] = None) -> bool:
    """Check whether a symbol is supported by the bot."""

    if whitelist is None:
        whitelist = [
            "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT",
            "TRX", "LINK", "MATIC", "LTC", "BCH", "ATOM", "NEAR", "FIL",
            "ICP", "ETC", "HBAR", "VET", "RUNE", "INJ", "OP", "ARB", "SUI",
            "STX", "TIA", "SEI", "1000PEPE",
        ]
    return symbol.upper() in whitelist


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("🔧 Binance API модуль запущено напряму.")
    logger.info("➡️ Поточний портфель:")
    for asset, value in get_current_portfolio().items():
        logger.info("• %s: $%.2f", asset, value)
