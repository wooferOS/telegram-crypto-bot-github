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

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
    raise ValueError(
        "BINANCE_API_KEY and BINANCE_SECRET_KEY must be provided in the environment"
    )
BINANCE_BASE_URL = "https://api.binance.com"

# File used to log TP/SL updates
LOG_FILE = "tp_sl_log.json"

# Cache for exchange information (12h TTL)
EXCHANGE_INFO_CACHE = "exchange_info_cache.json"
EXCHANGE_INFO_TTL = 60 * 60 * 12

# Cache for tradable USDT pairs loaded from Binance
cached_usdt_pairs: set[str] = set()


def normalize_symbol(symbol: str) -> str:
    """Return base symbol without the USDT suffix."""

    return symbol.upper().replace("USDT", "")


def _to_usdt_pair(symbol: str) -> str:
    """Return ``symbol`` formatted as a USDT trading pair without duplication."""

    token = symbol.upper().strip()
    if token.endswith("USDT"):
        return token
    pair = f"{token}USDT"
    assert not pair.endswith("USDTUSDT"), f"Invalid pair constructed: {pair}"
    return pair


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


def log_signal(message: str) -> None:
    """Append manual action signal to ``logs/trade.log``."""

    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} {message}\n"
    with open("logs/trade.log", "a", encoding="utf-8") as log_file:
        log_file.write(line)


def build_manual_conversion_signal(
    convert_from_list: list[dict], convert_to_suggestions: list[dict]
) -> str:
    """Return formatted manual conversion signal message.

    Only include conversions into non-USDT crypto with positive expected profit.
    If no valid suggestions remain, return an empty string.
    """

    msg = ["\ud83d\udd01 \u0423 \u0442\u0435\u0431\u0435 \u043d\u0430 \u0431\u0430\u043b\u0430\u043d\u0441\u0456 \u0442\u0440\u0435\u0431\u0430 \u0441\u043a\u043e\u043d\u0432\u0435\u0440\u0442\u0443\u0432\u0430\u0442\u0438 \u0437:"]
    for item in convert_from_list:
        sym = item.get("symbol")
        qty = round(float(item.get("quantity", 0)), 8)
        value = round(float(item.get("usdt_value", 0)), 2)
        msg.append(f"- {sym}: {qty} \u2248 {value} USDT")

    symbols_from = {item.get("symbol") for item in convert_from_list}
    candidates = []
    for suggestion in convert_to_suggestions:
        sym = suggestion.get("symbol")
        base = sym.replace("USDT", "") if sym else ""
        profit = float(suggestion.get("expected_profit_usdt", 0))
        if (
            base.upper() == "USDT"
            or profit <= 0
            or sym in symbols_from
            or f"{base}USDT" in symbols_from
        ):
            continue
        candidates.append(
            {
                "symbol": sym,
                "quantity": suggestion.get("quantity"),
                "expected_profit_usdt": profit,
            }
        )

    candidates.sort(key=lambda x: x["expected_profit_usdt"], reverse=True)

    selected: list[dict] = []
    used_targets: set[str] = set()
    for from_item in convert_from_list:
        from_sym = from_item.get("symbol", "").replace("USDT", "")
        for cand in candidates:
            target = cand["symbol"]
            base = target.replace("USDT", "")
            if (
                target in used_targets
                or base == from_sym
                or target in symbols_from
                or f"{base}USDT" in symbols_from
            ):
                continue
            selected.append(cand)
            used_targets.add(target)
            break

    if not selected:
        return ""

    msg.append(
        "\n\ud83d\udd01 \u041a\u043e\u043d\u0432\u0435\u0440\u0442\u0430\u0446\u0456\u044f \u043d\u0430:"
    )
    for suggestion in selected:
        sym = suggestion.get("symbol")
        qty = round(float(suggestion.get("quantity", 0)), 8)
        profit = round(float(suggestion.get("expected_profit_usdt", 0)), 2)
        msg.append(
            f"- {sym}: {qty} \u2192 \u043e\u0447\u0456\u043a\u0443\u0454\u0442\u044c\u0441\u044f \u043f\u0440\u0438\u0431\u0443\u0442\u043e\u043a \u2248 {profit} USDT"
        )

    return "\n".join(msg)


logger.debug(
    "[DEBUG] API: %s..., SECRET: %s...",
    BINANCE_API_KEY[:6],
    BINANCE_SECRET_KEY[:6],
)


# Initialise global Binance client exactly as in Binance docs
client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# Set of currently tradable USDT pairs
VALID_PAIRS: set[str] = set()


def refresh_valid_pairs() -> None:
    """Refresh ``VALID_PAIRS`` from Binance exchange info."""

    global VALID_PAIRS
    try:
        info = get_exchange_info_cached()
        VALID_PAIRS = {
            s["symbol"]
            for s in info.get("symbols", [])
            if s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
            and s.get("isSpotTradingAllowed")
        }
    except Exception as e:  # pragma: no cover - network errors
        logger.warning(f"⚠️ Не вдалося оновити VALID_PAIRS: {e}")


# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------

def is_symbol_valid(symbol: str) -> bool:
    """Return ``True`` if ``symbol`` is an active USDT pair."""

    pair = _to_usdt_pair(symbol)
    if not VALID_PAIRS:
        refresh_valid_pairs()
    is_valid = pair in VALID_PAIRS
    logger.info("is_symbol_valid(%s) -> %s (pair=%s)", symbol, is_valid, pair)
    return is_valid



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
    logger.debug("Loaded %d tradable USDT symbols", len(cached_usdt_pairs))
    return cached_usdt_pairs


def get_valid_symbols(quote: str = "USDT") -> list[str]:
    """Return list of tradable symbols quoted in ``quote``."""

    try:
        exchange_info = get_exchange_info_cached()
    except Exception as exc:  # pragma: no cover - network errors
        logger.error(
            "%s Не вдалося отримати exchange info: %s", TELEGRAM_LOG_PREFIX, exc
        )
        return []

    return [
        s["symbol"].upper()
        for s in exchange_info.get("symbols", [])
        if (
            s.get("quoteAsset") == quote
            and s.get("status") == "TRADING"
            and s.get("isSpotTradingAllowed")
        )
    ]


def get_valid_usdt_symbols() -> list[str]:
    """Return list of tradable USDT pairs from Binance."""

    return get_valid_symbols("USDT")

# Load available USDT trading pairs once on startup
refresh_valid_pairs()


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
        api_key = os.getenv("BINANCE_API_KEY")
        secret_key = os.getenv("BINANCE_SECRET_KEY")
        if not api_key or not secret_key:
            raise ValueError(
                "BINANCE_API_KEY and BINANCE_SECRET_KEY must be provided in the environment"
            )

        temp_client = Client(api_key, secret_key)

        logging.debug(
            "[DEBUG] API: %s..., SECRET: %s...",
            api_key[:8],
            secret_key[:8],
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


def get_non_usdt_assets(threshold_usd: float = 10) -> list[tuple[str, float, float]]:
    """Return non-USDT assets with value >= ``threshold_usd`` in USDT."""

    balances = get_balances()
    if balances.get("USDT", 0) > 0:
        return []

    prices = get_prices()
    assets: list[tuple[str, float, float]] = []
    for asset, amount in balances.items():
        if asset == "USDT":
            continue
        usd_value = amount * prices.get(asset, 0)
        if usd_value >= threshold_usd:
            assets.append((asset, amount, usd_value))
    return assets


def convert_small_balance(from_asset: str, to_asset: str = "USDT") -> None:
    """Convert ``from_asset`` to ``to_asset`` via Binance Convert API."""

    try:
        client.convert_trade(
            fromAsset=from_asset,
            toAsset=to_asset,
            amount=None,  # Binance визначає кількість автоматично
            type="MARKET",
        )
        logger.info(
            "\U0001F501 Конвертовано %s → %s через Binance Convert",
            from_asset,
            to_asset,
        )
    except BinanceAPIException as exc:
        logger.error(
            "\u274c Помилка конвертації %s → %s: %s",
            from_asset,
            to_asset,
            exc,
        )


def try_convert(
    symbol_from: str,
    symbol_to: str,
    amount: float,
    forecast: Optional[Dict[str, float]] | None = None,
) -> Optional[dict]:
    """Attempt conversion via Binance Convert API."""

    try:
        url = f"{BINANCE_BASE_URL}/sapi/v1/convert/getQuote"
        headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
        params: Dict[str, object] = {
            "fromAsset": symbol_from,
            "toAsset": symbol_to,
            "fromAmount": amount,
            "timestamp": get_timestamp(),
        }
        params["signature"] = client._generate_signature(params)
        response = requests.post(url, headers=headers, params=params, timeout=10)
        data = response.json()
        if "quoteId" not in data:
            raise Exception(data)

        quote_id = data["quoteId"]
        accept_url = f"{BINANCE_BASE_URL}/sapi/v1/convert/acceptQuote"
        accept_params = {
            "quoteId": quote_id,
            "timestamp": get_timestamp(),
        }
        accept_params["signature"] = client._generate_signature(accept_params)
        accept_resp = requests.post(
            accept_url, headers=headers, params=accept_params, timeout=10
        )
        result = accept_resp.json()
        if "orderId" not in result:
            raise Exception(result)
        return result
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("❌ Помилка при конвертації %s: %s", symbol_from, exc)
        price = None
        try:
            price = get_symbol_price(f"{symbol_from}{symbol_to}")
        except Exception:  # pragma: no cover - price fetch issues
            price = None
        usdt_price = price
        usdt_amount = round(float(amount) * usdt_price, 4) if usdt_price else "?"
        msg = (
            f"Сигнал: сконвертуйте {symbol_from} {amount} вручну на USDT ≈ {usdt_amount}"
            f" (1 {symbol_from} ≈ {usdt_price})"
        )
        logger.warning(msg)

        forecasted_price_next_1h15m = None
        if forecast:
            forecasted_price_next_1h15m = forecast.get("predicted_price") or forecast.get("forecast_1h15m")

        if forecasted_price_next_1h15m and isinstance(usdt_amount, (int, float)) and usdt_price:
            reverse_amount = usdt_amount / forecasted_price_next_1h15m
            reverse_profit = reverse_amount - amount
            logger.warning(
                f"⚠️ Якщо конвертуєш назад через 1г15х: отримаєш {reverse_amount:.4f} {symbol_from}. "
                f"Очікуваний прибуток: {reverse_profit:.4f} {symbol_from} "
                f"(\u043a\u0443\u0440\u0441 \u043e\u0447\u0456\u043a\u0443\u0454\u0442\u044c\u0441\u044f {forecasted_price_next_1h15m:.6f} USDT)"
            )

        log_signal(msg)
        return None


def convert_to_usdt(
    asset: str,
    amount: float,
    forecast: Optional[Dict[str, float]] | None = None,
):
    """Convert ``asset`` amount to USDT using Binance Convert API."""

    logger.info("🔁 Спроба конвертації %s %s в USDT", amount, asset)

    # Try client.convert_trade if available
    try:
        if hasattr(client, "convert_trade"):
            result = client.convert_trade(asset, "USDT", amount)
            if result.get("status") != "SUCCESS":
                raise Exception(f"Convert API повернув помилку: {result}")
            logger.info("✅ Конвертовано %s %s у USDT", amount, asset)
            return result
    except Exception as exc:  # pragma: no cover - handle below
        logger.warning("convert_trade fallback: %s", exc)

    return try_convert(asset, "USDT", amount, forecast)


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


def get_symbol_price(symbol: str) -> Optional[float]:
    """Return current price of ``symbol`` quoted in USDT."""

    pair = _to_usdt_pair(symbol)
    logger.debug("get_symbol_price: %s -> %s", symbol, pair)

    if not is_symbol_valid(symbol):
        logger.warning("⏭️ %s не торгується на Binance", pair)
        return None

    try:
        ticker = client.get_symbol_ticker(symbol=pair)
        return float(ticker.get("price", 0))
    except BinanceAPIException as exc:  # pragma: no cover - network errors
        if exc.code == -1121:
            logger.warning("⏭️ %s не торгується на Binance", pair)
        else:
            logger.error("❌ BinanceAPIException для %s: %s", pair, exc)
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("❌ Binance error for %s: %s", pair, exc)
    return None


def get_current_price(symbol: str) -> float:
    """Return current market price for a symbol."""

    pair = _to_usdt_pair(symbol)
    return get_symbol_price(pair)


def get_token_price(symbol: str) -> dict:
    """Return token price with symbol."""

    base = normalize_symbol(symbol)
    pair = f"{base}USDT".upper()
    if pair not in VALID_PAIRS:
        logger.warning("\u26a0\ufe0f \u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e %s: Token \u043d\u0435 \u0442\u043e\u0440\u0433\u0443\u0454\u0442\u044c\u0441\u044f \u043d\u0430 Binance", pair)
        return {"symbol": base, "price": "0"}
    try:
        ticker = client.get_symbol_ticker(symbol=pair)
        return {"symbol": base, "price": ticker.get("price", "0")}
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("\u274c Binance error for %s: %s", pair, exc)
        return {"symbol": base, "price": "0"}


def place_market_order(symbol: str, side: str, amount: float) -> Optional[Dict[str, object]]:
    """Place a market order for ``symbol`` on Binance."""

    base = normalize_symbol(symbol)
    pair = f"{base}USDT".upper()
    if pair not in VALID_PAIRS:
        logger.warning("⚠️ %s не знайдено у VALID_PAIRS, оновлюємо...", pair)
        refresh_valid_pairs()
        if pair not in VALID_PAIRS:
            logger.warning("⚠️ Після оновлення %s все ще не знайдено", pair)
            return None
    try:
        if side.upper() == "BUY":
            order = client.create_order(
                symbol=pair,
                side=Client.SIDE_BUY,
                type=Client.ORDER_TYPE_MARKET,
                quoteOrderQty=amount,
            )
        else:
            order = client.create_order(
                symbol=pair,
                side=Client.SIDE_SELL,
                type=Client.ORDER_TYPE_MARKET,
                quantity=amount,
            )
        print(f"✅ Order placed: {order}")
        return order
    except BinanceAPIException as e:
        print(f"❌ Order error for {pair}: {e}")
        if "LOT_SIZE" in str(e):
            result = convert_to_usdt(base, amount)
            if result is None:
                print("[WARN] convert failed")
        return None
    except Exception as e:
        print(f"❌ Order error for {pair}: {e}")
        return None


def market_buy_symbol_by_amount(symbol: str, amount: float) -> Dict[str, object]:
    """Buy ``symbol`` using market order for a specified USDT amount."""

    try:
        base = normalize_symbol(symbol)
        pair = f"{base}USDT".upper()
        if pair not in VALID_PAIRS:
            raise Exception(f"Token {pair} \u043d\u0435 \u0442\u043e\u0440\u0433\u0443\u0454\u0442\u044c\u0441\u044f \u043d\u0430 Binance")

        price = get_symbol_price(pair)
        if not price:
            raise Exception("Price unavailable")

        quantity = round(amount / price, 6)
        return client.create_order(
            symbol=pair,
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
        client.order_market_sell(symbol=symbol, quantity=quantity)
        logger.info("✅ Продано %s %s", quantity, symbol)
        return {"status": "success"}
    except BinanceAPIException as e:
        if "LOT_SIZE" in str(e):
            logger.warning(
                "⚠️ Не вдалося продати %s через LOT_SIZE — пробуємо конвертацію",
                symbol,
            )
            try:
                base_asset = symbol.replace("USDT", "")
                result = convert_to_usdt(base_asset, quantity)
                if result is None:
                    return {"status": "error", "message": "convert_failed"}
            except Exception as ce:  # pragma: no cover - network errors
                logger.error("❌ Помилка при конвертації %s: %s", symbol, ce)
                return {"status": "error", "message": str(ce)}
        else:
            logger.error("❌ Помилка при продажі %s: %s", symbol, e)
        return {"status": "error", "message": str(e)}


def sell_asset(symbol: str, quantity: float) -> dict:
    """Sell ``symbol`` with fallback to Binance Convert on LOT_SIZE error."""

    try:
        # звичайна спроба продати
        order = client.order_market_sell(symbol=symbol, quantity=round(quantity, 6))
        executed_qty = order["executedQty"]
        logger.info(
            "\u2705 Продано %s %s. Ордер ID: %s",
            executed_qty,
            symbol,
            order["orderId"],
        )
        return {
            "status": "success",
            "order_id": order["orderId"],
            "symbol": symbol,
            "executedQty": executed_qty,
        }
    except BinanceAPIException as e:
        if "LOT_SIZE" in str(e):
            logger.warning("\u2757 LOT_SIZE error, спроба конвертації %s → USDT", symbol)
            try:
                base_asset = symbol.replace("USDT", "")
                result = convert_to_usdt(base_asset, quantity)
                if result is not None:
                    return {"status": "converted"}
                return {"status": "error", "message": "convert_failed"}
            except Exception as conv_e:  # pragma: no cover - network errors
                logger.error("\u26D4\ufe0f Помилка при конвертації %s: %s", symbol, conv_e)
                return {"status": "error", "message": str(conv_e)}
        raise

def place_sell_order(symbol: str, quantity: float, price: float) -> bool:
    """Place a limit sell order on Binance."""

    try:
        pair = _to_usdt_pair(symbol)
        order = client.create_order(
            symbol=pair,
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
    pair = _to_usdt_pair(symbol)
    price = get_symbol_price(pair)
    try:
        order = client.create_order(
            symbol=pair,
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
        pair = _to_usdt_pair(symbol)
        order = client.create_order(
            symbol=pair,
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
        pair = _to_usdt_pair(symbol)
        order = client.create_order(
            symbol=pair,
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

    pair = _to_usdt_pair(symbol)

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

    pair = _to_usdt_pair(symbol)
    orders = get_open_orders(pair)
    if not orders:
        return

    current = get_symbol_price(pair)
    if current is None:
        return
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

    pair = _to_usdt_pair(symbol)
    price = get_symbol_price(pair)
    if price is None:
        return 0.0
    return round(price * get_usdt_to_uah_rate(), 2)


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
    pair = _to_usdt_pair(symbol)
    try:
        resp = requests.get(url, params={"symbol": pair}, timeout=5)
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
    pair = _to_usdt_pair(symbol)
    params = {"symbol": pair, "interval": "1h", "limit": 24}
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
    pair = _to_usdt_pair(symbol)
    assert not pair.endswith("USDTUSDT"), f"Invalid pair {pair}"
    logger.debug("get_candlestick_klines: %s -> %s", symbol, pair)
    params = {"symbol": pair, "interval": interval, "limit": limit}
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
            pair = _to_usdt_pair(asset)
            trades = client.get_my_trades(symbol=pair, limit=5)
            if not trades:
                continue

            total_cost = sum(float(t["price"]) * float(t["qty"]) for t in trades)
            total_qty = sum(float(t["qty"]) for t in trades)

            if total_qty == 0:
                continue

            avg_price = total_cost / total_qty
            current_price = get_symbol_price(pair)
            if current_price is None:
                continue
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


def _expected_profit(price: float, tp: float, amount: float, sl: float) -> float:
    """Calculate simple expected profit used for top token preview."""

    if price <= 0 or tp <= price:
        return 0.0
    gross = (tp - price) * amount / price
    net = gross * (1 - 2 * 0.001)
    adj = net * 0.65
    if sl and sl < price:
        loss = (price - sl) * amount / price
        exp_loss = loss * (1 - 0.65)
        return round(adj - exp_loss, 2)
    return round(adj, 2)


def get_top_tokens(limit: int = 50) -> List[Dict[str, object]]:
    """Return detailed info for top tokens by 24h volume."""

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

        result: List[Dict[str, object]] = []
        for item in sorted_tokens[:limit]:
            symbol = item["symbol"].replace("USDT", "")
            price = float(item.get("lastPrice", 0))
            high = float(item.get("highPrice", 0))
            low = float(item.get("lowPrice", 0))

            if price - low > 0:
                risk_reward = round((high - price) / (price - low), 2)
            else:
                risk_reward = 0.0

            momentum = float(item.get("priceChangePercent", 0))
            tp_price = round(price * 1.10, 6)
            sl_price = round(price * 0.95, 6)
            expected_profit = _expected_profit(price, tp_price, 10, sl_price)

            score = round(risk_reward * 2 + (1.5 if momentum > 0 else 0), 2)

            result.append(
                {
                    "symbol": symbol,
                    "risk_reward": risk_reward,
                    "expected_profit": expected_profit,
                    "score": score,
                    "momentum": momentum,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                }
            )

        return result
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

        pair = _to_usdt_pair(symbol)
        params = {
            "symbol": pair,
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

        pair = _to_usdt_pair(symbol)
        params = {
            "symbol": pair,
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
    base = normalize_symbol(symbol)
    if base not in load_tradable_usdt_symbols():
        raise ValueError(f"Token {base} не торгується на Binance")
    pair = _to_usdt_pair(symbol)
    assert not pair.endswith("USDTUSDT"), f"Invalid pair {pair}"
    logger.debug(
        "get_candlestick_klines(daily): %s -> %s interval=%s", symbol, pair, interval
    )
    return client.get_klines(
        symbol=pair,
        interval=interval,
        limit=limit,
    )


def test_valid_pairs() -> None:
    """Log availability of some common USDT pairs."""

    test_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "XRPUSDT"]
    for symbol in test_symbols:
        if symbol not in VALID_PAIRS:
            logger.warning(f"❌ {symbol} — Немає в VALID_PAIRS!")
        else:
            logger.info(f"✅ {symbol} — OK")


