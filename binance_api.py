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
import math
import json
from datetime import datetime
from typing import Dict, List, Optional

import requests
from binance.client import Client
from binance.enums import (
    SIDE_BUY,
    SIDE_SELL,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC,
    ORDER_TYPE_STOP_LOSS_LIMIT,
)
from binance.exceptions import BinanceAPIException


logger = logging.getLogger(__name__)
TELEGRAM_LOG_PREFIX = "\ud83d\udce1 [BINANCE]"

from config import (
    BINANCE_API_KEY,
    BINANCE_SECRET_KEY,
    TELEGRAM_TOKEN,
    CHAT_ID,
)
BINANCE_BASE_URL = "https://api.binance.com"

# File used to log TP/SL updates
LOG_FILE = "tp_sl_log.json"

# Cache for exchange information (12h TTL)
EXCHANGE_INFO_CACHE = "exchange_info_cache.json"
EXCHANGE_INFO_TTL = 60 * 60 * 12

# Cache for tradable USDT pairs loaded from Binance
cached_usdt_pairs: set[str] = set()


def log_tp_sl_change(symbol: str, action: str, tp: float, sl: float) -> None:
    """Append TP/SL change information to ``LOG_FILE``."""

    log_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "action": action,
        "take_profit": tp,
        "stop_loss": sl,
    }

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = []

    history.append(log_data)

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


print(f"[DEBUG] API: {BINANCE_API_KEY[:6]}..., SECRET: {BINANCE_SECRET_KEY[:6]}...")


# Initialise global Binance client exactly as in Binance docs
client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)


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


def get_exchange_info_cached() -> Dict[str, object]:
    """Return exchangeInfo using local cache with 12h TTL."""

    if os.path.exists(EXCHANGE_INFO_CACHE):
        mtime = os.path.getmtime(EXCHANGE_INFO_CACHE)
        if time.time() - mtime < EXCHANGE_INFO_TTL:
            with open(EXCHANGE_INFO_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)

    info = client.get_exchange_info()
    with open(EXCHANGE_INFO_CACHE, "w", encoding="utf-8") as f:
        json.dump(info, f)
    return info


def get_exchange_info() -> Dict[str, object]:
    """Return exchange information directly from Binance without cache."""

    return client.get_exchange_info()


def load_tradable_usdt_symbols() -> set[str]:
    """Return cached set of tradable symbols quoted in USDT."""

    global cached_usdt_pairs
    if cached_usdt_pairs:
        return cached_usdt_pairs
    info = get_exchange_info()
    pairs = [
        s["symbol"]
        for s in info.get("symbols", [])
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    ]
    cached_usdt_pairs = {p.replace("USDT", "") for p in pairs}
    return cached_usdt_pairs


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
            BINANCE_API_KEY,
            BINANCE_SECRET_KEY,
        )

        logging.debug(
            f"[DEBUG] API: {BINANCE_API_KEY[:8]}..., SECRET: {BINANCE_SECRET_KEY[:8]}..."
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


def get_dust_assets() -> List[str]:
    """Return list of assets with total value less than 1 USDT."""

    prices = get_prices()
    balances = get_balances()
    dust = []
    for asset, amount in balances.items():
        if asset == "USDT":
            continue
        value = amount * prices.get(asset, 0)
        if value < 1:
            dust.append(asset)
    return dust


def convert_dust_to_usdt(assets: Optional[List[str]] = None) -> Optional[dict]:
    """Convert small balances into USDT using Binance dust API."""

    if assets is None:
        assets = get_dust_assets()
    if not assets:
        return None
    params = {"timestamp": get_timestamp()}
    for idx, asset in enumerate(assets):
        params[f"asset{idx}"] = asset
    signed = sign_request(params)
    url = f"{BINANCE_BASE_URL}/sapi/v1/asset/dust"
    try:
        resp = requests.post(url, headers=get_headers(), params=signed, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("[ERROR] convert_dust_to_usdt: %s", exc)
        return None


def get_account_balances() -> Dict[str, Dict[str, str]]:
    """Return mapping of assets to their free and locked amounts."""

    try:
        account = client.get_account()
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("%s Не вдалося отримати баланси акаунта: %s", TELEGRAM_LOG_PREFIX, exc)
        return {}

    balances: Dict[str, Dict[str, str]] = {}
    for bal in account.get("balances", []):
        balances[bal.get("asset", "")] = {
            "free": bal.get("free", "0"),
            "locked": bal.get("locked", "0"),
        }

    return balances


def get_asset_quantity(symbol: str) -> float:
    """Return available quantity for ``symbol`` using account balances."""

    asset = symbol.replace("USDT", "").upper()
    balances = get_account_balances()
    return float(balances.get(asset, {}).get("free", 0))


def cancel_all_orders(symbol: str) -> None:
    """Cancel all open orders for ``symbol``."""

    try:
        client.cancel_open_orders(symbol=symbol)
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("❌ Не вдалося скасувати ордери для %s: %s", symbol, exc)


def get_symbol_price(symbol: str) -> float:
    """Return current price of token to USDT."""

    try:
        ticker = client.get_symbol_ticker(symbol=f"{symbol.upper()}USDT")
        return float(ticker.get("price", 0))
    except Exception as exc:
        logger.error("%s Помилка ціни для %s: %s", TELEGRAM_LOG_PREFIX, symbol, exc)
        return 0.0


def get_current_price(symbol: str) -> float:
    """Return current market price for a symbol."""

    return get_symbol_price(symbol)


def get_token_price(symbol: str) -> dict:
    """Return token price with symbol."""

    try:
        ticker = client.get_symbol_ticker(symbol=f"{symbol.upper()}USDT")
        return {"symbol": symbol.upper(), "price": ticker.get("price", "0")}
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("%s Помилка при отриманні ціни %s: %s", TELEGRAM_LOG_PREFIX, symbol, exc)
        return {"symbol": symbol.upper(), "price": "0"}


def place_market_order(symbol: str, side: str, usdt_amount: float) -> Optional[Dict[str, object]]:
    """Execute a market order on a USDT amount and set Take Profit on buy."""

    try:
        price = get_current_price(symbol)
        if not price:
            return None

        quantity = round(usdt_amount / price, 6)

        order = client.create_order(
            symbol=f"{symbol.upper()}USDT",
            side=SIDE_BUY if side.upper() == "BUY" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
        )
        logger.info("%s Ордер %s виконано: %s", TELEGRAM_LOG_PREFIX, side, order)

        if side.upper() == "BUY" and order.get("status") == "FILLED":
            # Встановлення Take Profit (TP) після покупки
            executed_qty = float(order.get("executedQty", quantity))
            if current_price := get_symbol_price(symbol):
                take_profit_price = round(current_price * 1.10, 5)
                place_limit_sell_order(
                    f"{symbol.upper()}USDT",
                    executed_qty,
                    take_profit_price,
                )

        return order

    except BinanceAPIException as e:
        logger.error(
            "%s \u274c Помилка при створенні ордера %s для %s: %s",
            TELEGRAM_LOG_PREFIX,
            side,
            symbol,
            e,
        )
        return None


def market_buy_symbol_by_amount(symbol: str, amount: float) -> Dict[str, object]:
    """Buy ``symbol`` using market order for a specified USDT amount."""

    try:
        price = get_current_price(symbol)
        if not price:
            raise Exception("Price unavailable")

        quantity = round(amount / price, 6)
        return client.create_order(
            symbol=f"{symbol.upper()}USDT",
            side=SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
        )
    except BinanceAPIException as e:  # pragma: no cover - network errors
        raise Exception(f"Binance API error: {e.message}")
    except Exception as exc:
        raise Exception(f"Unexpected error: {exc}")

def market_buy(symbol: str, usdt_amount: float) -> dict:
    """Ринкова купівля ``symbol`` на вказану суму в USDT."""

    try:
        price_data = client.get_symbol_ticker(symbol=symbol)
        current_price = float(price_data["price"])

        quantity = round(usdt_amount / current_price, 6)

        order = client.order_market_buy(symbol=symbol, quantity=quantity)

        logger.info(
            f"\u2705 Куплено {quantity} {symbol} на {usdt_amount} USDT. Ордер ID: {order['orderId']}"
        )
        return {
            "status": "success",
            "order_id": order["orderId"],
            "symbol": symbol,
            "executedQty": order["executedQty"],
            "price": current_price,
        }

    except BinanceAPIException as e:
        logger.error(f"\u274c Помилка при ринковій купівлі {symbol}: {str(e)}")
        return {"status": "error", "message": str(e)}


def market_sell(symbol: str, quantity: float) -> dict:
    """Виконує ринковий продаж криптовалюти на вказану кількість."""

    try:
        order = client.order_market_sell(
            symbol=symbol,
            quantity=round(quantity, 6),
        )

        executed_qty = order["executedQty"]
        logger.info(
            f"\u2705 Продано {executed_qty} {symbol}. Ордер ID: {order['orderId']}"
        )
        return {
            "status": "success",
            "order_id": order["orderId"],
            "symbol": symbol,
            "executedQty": executed_qty,
        }

    except BinanceAPIException as e:
        logger.error(f"\u274c Помилка при ринковому продажі {symbol}: {str(e)}")
        return {"status": "error", "message": str(e)}


def sell_asset(symbol: str, amount: float) -> dict:
    """Sell ``amount`` of ``symbol`` using market order with step rounding."""

    step = get_lot_step(symbol)

    adjusted_amount = math.floor(amount / step) * step
    adjusted_amount = round(adjusted_amount, int(abs(math.log10(step))))

    logger.info(
        f"[dev] \u2699\ufe0f \u041e\u043a\u0440\u0443\u0433\u043b\u0435\u043d\u0430 \u043a\u0456\u043b\u044c\u043a\u0456\u0441\u0442\u044c {symbol}: {adjusted_amount} (step={step})"
    )
    result = market_sell(symbol, adjusted_amount)
    return result

def place_sell_order(symbol: str, quantity: float, price: float) -> bool:
    """Place a limit sell order on Binance."""

    try:
        order = client.create_order(
            symbol=symbol.upper() + "USDT",
            side="SELL",
            type="LIMIT",
            timeInForce="GTC",
            quantity=round(quantity, 6),
            price=str(round(price, 5)),
        )
        return True
    except Exception as e:  # pragma: no cover - network errors
        print(f"[ERROR] Failed to place take profit order for {symbol}: {e}")
        return False


def place_limit_sell(symbol: str, quantity: float) -> dict:
    """Place a LIMIT sell order at current market price."""
    price = get_symbol_price(symbol)
    try:
        order = client.create_order(
            symbol=f"{symbol.upper()}USDT",
            side="SELL",
            type="LIMIT",
            timeInForce="GTC",
            quantity=round(quantity, 6),
            price=str(round(price, 6)),
        )
        return {"success": True, "order": order}
    except Exception as exc:  # pragma: no cover - network errors
        logger.error(
            "%s Failed to place limit sell for %s: %s",
            TELEGRAM_LOG_PREFIX,
            symbol,
            exc,
        )
        return {"success": False, "error": str(exc)}




def place_take_profit_order(
    symbol: str,
    quantity: float,
    take_profit_price: float | None = None,
    *,
    current_price: float | None = None,
    profit_percent: float = 10.0,
) -> Optional[Dict[str, object]]:
    """Створює ордер Take Profit.

    Якщо ``take_profit_price`` не вказаний, він розраховується від
    ``current_price`` з урахуванням ``profit_percent``.
    """

    if take_profit_price is None:
        if current_price is None:
            raise ValueError("current_price or take_profit_price required")
        take_profit_price = round(current_price * (1 + profit_percent / 100), 8)

    try:
        response = client.create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type=ORDER_TYPE_LIMIT,
            quantity=quantity,
            timeInForce=TIME_IN_FORCE_GTC,
            price=str(take_profit_price),
        )
        logger.info(
            f"\u2705 Take Profit ордер створено для {symbol} на ціні {take_profit_price}"
        )
        return response
    except BinanceAPIException as e:
        logger.error(
            f"\u274c Помилка при створенні Take Profit ордера для {symbol}: {e}"
        )
        return None


def create_take_profit_order(symbol: str, quantity: float, target_price: float) -> dict:
    """Створення ордера LIMIT SELL для фіксації прибутку (Take Profit)"""

    try:
        price_str = f"{target_price:.8f}".rstrip("0").rstrip(".")
        quantity_str = f"{quantity:.8f}".rstrip("0").rstrip(".")
        order = client.create_order(
            symbol=symbol,
            side='SELL',
            type='LIMIT',
            timeInForce='GTC',
            quantity=quantity_str,
            price=price_str,
        )
        return {"success": True, "order": order}
    except Exception as e:  # pragma: no cover - network errors
        return {"success": False, "error": str(e)}


def place_stop_limit_buy_order(
    symbol: str, quantity: float, stop_price: float, limit_price: float
) -> dict:
    """Create STOP_LIMIT BUY order on Binance."""

    try:
        order = client.create_order(
            symbol=f"{symbol.upper()}USDT",
            side="BUY",
            type="STOP_LOSS_LIMIT",
            timeInForce="GTC",
            quantity=round(quantity, 6),
            price=str(round(limit_price, 6)),
            stopPrice=str(round(stop_price, 6)),
        )
        return order
    except Exception as exc:  # pragma: no cover - network errors
        logger.error(
            "%s Не вдалося створити STOP_LIMIT BUY для %s: %s",
            TELEGRAM_LOG_PREFIX,
            symbol,
            exc,
        )
        return {"error": str(exc)}


def place_stop_limit_sell_order(
    symbol: str, quantity: float, stop_price: float, limit_price: float
) -> dict:
    """Create STOP_LIMIT SELL order on Binance."""

    try:
        order = client.create_order(
            symbol=f"{symbol.upper()}USDT",
            side="SELL",
            type="STOP_LOSS_LIMIT",
            timeInForce="GTC",
            quantity=round(quantity, 6),
            price=str(round(limit_price, 6)),
            stopPrice=str(round(stop_price, 6)),
        )
        return order
    except Exception as exc:  # pragma: no cover - network errors
        logger.error(
            "%s Не вдалося створити STOP_LIMIT SELL для %s: %s",
            TELEGRAM_LOG_PREFIX,
            symbol,
            exc,
        )
        return {"error": str(exc)}


def place_stop_loss_order(
    symbol: str, quantity: float, stop_price: float
) -> Optional[Dict[str, object]]:
    """Створити стандартний Stop Loss ордер."""

    try:
        order = client.create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type=ORDER_TYPE_STOP_LOSS_LIMIT,
            timeInForce=TIME_IN_FORCE_GTC,
            quantity=round(quantity, 6),
            price=str(stop_price),
            stopPrice=str(stop_price),
        )
        logger.info(
            "\U0001F6E1\ufe0f Stop Loss ордер створено для %s на ціні %s",
            symbol,
            stop_price,
        )
        return order
    except BinanceAPIException as e:  # pragma: no cover - network errors
        logger.error(
            "\u274c Помилка при створенні Stop Loss ордера для %s: %s",
            symbol,
            e,
        )
        return None


def get_open_orders(symbol: str | None = None) -> list:
    """Return all open orders using a signed HTTP request."""

    endpoint = "/api/v3/openOrders"
    params: Dict[str, object] = {"timestamp": get_timestamp()}
    if symbol:
        params["symbol"] = symbol.upper()
    signed_params = sign_request(params)
    url = f"{BINANCE_BASE_URL}{endpoint}"
    try:
        resp = requests.get(url, headers=get_headers(), params=signed_params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning("%s Не вдалося отримати відкриті ордери: %s", TELEGRAM_LOG_PREFIX, exc)
        return []


def cancel_order(order_id: int, symbol: str = "USDTBTC") -> bool:
    """Cancel an existing order by ID."""
    try:
        response = client.cancel_order(symbol=symbol, orderId=order_id)
        return response.get("status") == "CANCELED"
    except Exception as e:
        logger.error("[ERROR] cancel_order: %s", e)
        return False


def update_tp_sl_order(symbol: str, new_tp_price: float, new_sl_price: float) -> Dict[str, int] | None:
    """Refresh TP/SL orders for ``symbol`` with new prices."""

    pair = symbol.upper() if symbol.upper().endswith("USDT") else f"{symbol.upper()}USDT"

    cancel_all_orders(pair)

    quantity = get_asset_quantity(pair)
    tp = place_limit_sell_order(pair, quantity=quantity, price=new_tp_price)
    sl = place_stop_limit_sell_order(symbol.replace("USDT", ""), quantity=quantity, stop_price=new_sl_price, limit_price=new_sl_price * 0.995)

    if isinstance(tp, dict) and isinstance(sl, dict) and tp.get("orderId") and sl.get("orderId"):
        return {"tp": tp.get("orderId"), "sl": sl.get("orderId")}

    logger.error("[ERROR] update_tp_sl_order: failed to place TP/SL for %s", symbol)
    return None


def modify_order(symbol: str, new_tp: float, new_sl: float) -> bool:
    """Public wrapper to update TP/SL and log the change."""

    result = update_tp_sl_order(symbol, new_tp, new_sl)
    if result:
        log_tp_sl_change(symbol, "modify", new_tp, new_sl)
        return True
    return False


def cancel_tp_sl_if_market_changed(symbol: str) -> None:
    """Cancel TP/SL orders if market price moved more than 5%."""

    pair = symbol.upper() if symbol.upper().endswith("USDT") else f"{symbol.upper()}USDT"
    orders = get_open_orders(pair)
    if not orders:
        return

    current = get_symbol_price(symbol)
    for o in orders:
        if o.get("side") != "SELL":
            continue
        if o.get("type") == "LIMIT":
            price = float(o.get("price", 0))
        elif o.get("type") == "STOP_LOSS_LIMIT":
            price = float(o.get("stopPrice", 0))
        else:
            continue
        if price and abs(current - price) / price > 0.05:
            cancel_order(int(o["orderId"]), pair)


def get_active_orders() -> Dict[str, object]:
    """Return stored active TP/SL orders from ``active_orders.json``."""

    try:
        with open("active_orders.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


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

    token = TELEGRAM_TOKEN
    chat_id = CHAT_ID
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
    try:
        data = get_exchange_info_cached()
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


def get_lot_step(symbol: str) -> float:
    """Return LOT_SIZE step for symbol."""
    try:
        data = get_exchange_info_cached()
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        return float(f.get("stepSize"))
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning(
            "%s Помилка при отриманні stepSize для %s: %s",
            TELEGRAM_LOG_PREFIX,
            symbol,
            exc,
        )
    return 1.0


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


def get_candlestick_klines(symbol: str, interval: str = "1h", limit: int = 100) -> List[List[float]]:
    """Return raw candlestick klines for a symbol."""
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": f"{symbol.upper()}USDT", "interval": interval, "limit": limit}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:  # pragma: no cover - network errors
        logger.warning("❌ Klines error for %s: %s", symbol, e)
        return []


def get_recent_trades(symbol: str = "BTCUSDT", limit: int = 5) -> List[Dict[str, object]]:
    """Return recent trades from Binance."""

    try:
        return client.get_my_trades(symbol=symbol, limit=limit)
    except Exception as exc:
        logger.warning(
            "%s Помилка при отриманні історії угод: %s", TELEGRAM_LOG_PREFIX, exc
        )
        return []


def get_real_pnl_data() -> Dict[str, Dict[str, float]]:
    """Return real-time PnL data from Binance (current vs avg price)."""
    account = get_account_info()
    result: Dict[str, Dict[str, float]] = {}
    if not account:
        return result

    for pos in account.get("balances", []):
        asset = pos["asset"]
        amount = float(pos.get("free", 0))
        if amount == 0 or asset == "USDT":
            continue

        try:
            trades = client.get_my_trades(symbol=f"{asset}USDT", limit=5)
            if not trades:
                continue

            total_cost = sum(float(t["price"]) * float(t["qty"]) for t in trades)
            total_qty = sum(float(t["qty"]) for t in trades)

            if total_qty == 0:
                continue

            avg_price = total_cost / total_qty
            current_price = get_symbol_price(asset)
            pnl_percent = round((current_price - avg_price) / avg_price * 100, 2)

            result[asset] = {
                "amount": amount,
                "avg_price": round(avg_price, 6),
                "current_price": current_price,
                "pnl_percent": pnl_percent,
            }

        except Exception as exc:  # pragma: no cover - network errors
            logger.warning("%s PnL skip %s: %s", TELEGRAM_LOG_PREFIX, asset, exc)

    return result


def get_portfolio_stats() -> Dict[str, float]:
    """Return total portfolio value both in USDT and UAH."""

    portfolio = get_current_portfolio()
    total_usdt = sum(portfolio.values())
    total_uah = round(total_usdt * get_usdt_to_uah_rate(), 2)
    return {"total_usdt": round(total_usdt, 4), "total_uah": total_uah}


def get_all_spot_symbols() -> List[str]:
    """Return list of all tradable spot symbols (USDT pairs)."""

    try:
        info = get_exchange_info_cached()
        return [
            s["baseAsset"]
            for s in info.get("symbols", [])
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
        ]
    except Exception as exc:
        logger.warning(
            "%s Помилка при отриманні списку токенів: %s",
            TELEGRAM_LOG_PREFIX,
            exc,
        )
        return []


def get_tradable_usdt_symbols() -> List[str]:
    """Return list of tradable symbols that have an active USDT pair."""

    try:
        info = get_exchange_info_cached()
        usdt_pairs = [
            s.get("symbol")
            for s in info.get("symbols", [])
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
        ]
        return list({s.replace("USDT", "") for s in usdt_pairs})
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning(
            "%s \u041f\u043e\u043c\u0438\u043b\u043a\u0430 \u043f\u0440\u0438 \u043e\u0442\u0440\u0438\u043c\u0430\u043d\u043d\u0456 USDT \u0442\u043e\u043a\u0435\u043d\u0456\u0432: %s",
            TELEGRAM_LOG_PREFIX,
            exc,
        )
        return []


def get_top_tokens(limit: int = 50) -> List[str]:
    """Return top tokens by 24h volume."""

    url = f"{BINANCE_BASE_URL}/api/v3/ticker/24hr"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        filtered = [
            item
            for item in data
            if str(item.get("symbol", "")).endswith("USDT")
        ]
        sorted_tokens = sorted(
            filtered,
            key=lambda x: float(x.get("quoteVolume", 0)),
            reverse=True,
        )
        return [
            item["symbol"].replace("USDT", "")
            for item in sorted_tokens[:limit]
        ]
    except Exception as exc:
        logger.warning(
            "%s Помилка при отриманні топ токенів: %s",
            TELEGRAM_LOG_PREFIX,
            exc,
        )
        return []


def is_asset_supported(symbol: str, whitelist: Optional[List[str]] = None) -> bool:
    """Check whether a symbol is supported by the bot."""

    if whitelist is None:
        whitelist = get_all_spot_symbols()

    whitelist = [s.upper() for s in whitelist]
    return symbol.upper() in whitelist


def get_all_tokens_with_balance(threshold: float = 0.00001) -> list:
    """Return list of all tokens with non-zero balance"""
    info = get_account_info()
    tokens = []

    for asset in info.get("balances", []):
        free = float(asset.get("free", 0))
        if free > threshold:
            tokens.append(asset["asset"])

    return tokens


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("🔧 Binance API модуль запущено напряму.")
    logger.info("➡️ Поточний портфель:")
    for asset, value in get_current_portfolio().items():
        logger.info("• %s: $%.2f", asset, value)


def place_limit_sell_order(symbol: str, quantity: float, price: float) -> dict:
    """
    Виставляє лімітний ордер на продаж з ціною Take Profit.
    """
    try:
        response = client.create_order(
            symbol=symbol,
            side=Client.SIDE_SELL,
            type=Client.ORDER_TYPE_LIMIT,
            timeInForce=Client.TIME_IN_FORCE_GTC,
            quantity=round(quantity, 5),
            price=str(price)
        )
        logger.info(f"✅ Виставлено лімітний ордер на продаж {symbol} по {price}")
        return response
    except BinanceAPIException as e:
        logger.error(f"❌ Помилка при виставленні TP ордера для {symbol}: {e}")
        return {"error": str(e)}


def place_take_profit_order_auto(symbol: str, quantity: float | None = None, target_price: float = 0.0) -> dict:
    """Виставляє Take Profit ордер із автоматичним розрахунком кількості."""

    try:
        if quantity is None:
            balance = get_token_balance(symbol.replace("USDT", ""))
            quantity = round(balance * 0.99, 5)

        params = {
            "symbol": symbol.upper() if symbol.upper().endswith("USDT") else symbol.upper() + "USDT",
            "side": "SELL",
            "type": "LIMIT",
            "quantity": quantity,
            "price": str(target_price),
            "timeInForce": "GTC",
        }
        signed_params = sign_request(params)
        response = requests.post(
            f"{BINANCE_BASE_URL}/api/v3/order", headers=get_headers(), params=signed_params
        )
        return response.json()
    except Exception as e:  # pragma: no cover - network errors
        return {"error": str(e)}


def place_stop_loss_order_auto(symbol: str, quantity: float | None = None, stop_price: float = 0.0) -> dict:
    """Виставляє Stop Loss ордер із автоматичним розрахунком кількості."""

    try:
        if quantity is None:
            balance = get_token_balance(symbol.replace("USDT", ""))
            quantity = round(balance * 0.99, 5)

        params = {
            "symbol": symbol.upper() if symbol.upper().endswith("USDT") else symbol.upper() + "USDT",
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "quantity": quantity,
            "stopPrice": str(stop_price),
            "price": str(stop_price),
            "timeInForce": "GTC",
        }
        signed_params = sign_request(params)
        response = requests.post(
            f"{BINANCE_BASE_URL}/api/v3/order", headers=get_headers(), params=signed_params
        )
        return response.json()
    except Exception as e:  # pragma: no cover - network errors
        return {"error": str(e)}

# Alias для сумісності з існуючим кодом
sell_token_market = market_sell

# ✅ Compatibility alias
buy_token_market = market_buy


def get_candlestick_klines(symbol: str, interval: str = "1d", limit: int = 7):
    """Return candlestick klines for a tradable symbol."""

    if symbol not in load_tradable_usdt_symbols():
        raise ValueError(f"Token {symbol} не торгується на Binance")
    return client.get_klines(
        symbol=f"{symbol.upper()}USDT",
        interval=interval,
        limit=limit,
    )


