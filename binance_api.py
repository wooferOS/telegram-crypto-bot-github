


# pylint: disable=missing-docstring
"""Binance API helper module.

This module provides synchronous helpers for interacting with the Binance Spot
API and is designed for use in a Telegram bot.
"""

from __future__ import annotations
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_session = requests.Session()
retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])

adapter = HTTPAdapter(max_retries=retries)
_session.mount("https://", adapter)





import os
import time
import hmac
import hashlib
from utils import logger
from log_setup import setup_logging
import decimal
from decimal import Decimal, getcontext
import json
import math
from datetime import datetime
from typing import Dict, List, Optional

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



# ``logger`` is provided by utils
TELEGRAM_LOG_PREFIX = "\ud83d\udce1 [BINANCE]"

from config import (
    BINANCE_API_KEY,
    BINANCE_SECRET_KEY,
    TELEGRAM_TOKEN,
    CHAT_ID,
    ADMIN_CHAT_ID,
    BINANCE_TEST_MODE,
)

TEST_MODE = BINANCE_TEST_MODE

# Credentials are provided via ``config.py`` on the server.
BINANCE_BASE_URL = "https://api.binance.com"

# File used to log TP/SL updates
LOG_FILE = "tp_sl_log.json"

# Cache for exchange information (12h TTL)
EXCHANGE_INFO_CACHE = "exchange_info_cache.json"
EXCHANGE_INFO_TTL = 60 * 60 * 12

# Cache for tradable USDT pairs loaded from Binance
cached_usdt_pairs: set[str] = set()

# Cached exchange info for quick LOT_SIZE lookup
exchange_info: dict[str, dict] = {}


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


def adjust_qty_to_step(qty: float, step: Decimal) -> float:
    """Round ``qty`` down to the nearest ``step`` size."""

    q = Decimal(str(qty))
    adjusted = (q // step) * step
    result = float(adjusted)
    logger.info("step_size=%s adjusted_qty=%s", step, result)
    return result


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



if BINANCE_API_KEY and BINANCE_SECRET_KEY:
    logger.debug(
        "API: %s..., SECRET: %s...",
        BINANCE_API_KEY[:6],
        BINANCE_SECRET_KEY[:6],
    )
else:
    logger.error("Binance API keys are not loaded. Check config.py on the server.")



# Initialise Binance client explicitly using credentials from ``config.py``
client: Client | None = None

if not BINANCE_TEST_MODE:
    client = Client(
        api_key=BINANCE_API_KEY,
        api_secret=BINANCE_SECRET_KEY,
    )
    try:
        client.ping()
    except Exception as e:
        logger.warning("[dev] \u2757 Binance ping failed: %s", e)


def _get_client() -> Client:
    """Return cached Binance ``Client`` instance."""
    global client
    if client is None:
        if TEST_MODE:
            raise RuntimeError("Binance client unavailable in test mode")
        if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
            raise RuntimeError("Binance API keys are missing")
        client = Client(
            BINANCE_API_KEY,
            BINANCE_SECRET_KEY,
        )
        if not BINANCE_TEST_MODE:
            try:
                client.ping()
            except Exception as e:
                logger.warning("[dev] \u2757 Binance ping failed: %s", e)
    return client


def get_binance_client() -> Client:
    """Return a fresh Binance ``Client`` using credentials from config."""

    client_obj = Client(
        api_key=BINANCE_API_KEY,
        api_secret=BINANCE_SECRET_KEY,
    )
    if not BINANCE_TEST_MODE:
        try:
            client_obj.ping()
        except Exception as e:
            logger.warning("[dev] \u2757 Binance ping failed: %s", e)
    return client_obj

# Set of currently tradable USDT pairs
VALID_PAIRS: set[str] = set()


def refresh_valid_pairs() -> None:
    """Refresh ``VALID_PAIRS`` from Binance exchange info."""

    global VALID_PAIRS
    VALID_PAIRS.clear()
    try:
        data = client.get_exchange_info()
        all_pairs = [
            s["symbol"]
            for s in data["symbols"]
            if s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"
            and s["isSpotTradingAllowed"]
            and not s["symbol"].startswith(("USD", "BUSD", "TUSD"))
        ][:100]
        VALID_PAIRS.update(all_pairs)
        logger.info("✅ VALID_PAIRS оновлено: %d пар", len(VALID_PAIRS))
    except Exception as e:  # pragma: no cover - network errors
        logger.warning("❌ Не вдалося оновити VALID_PAIRS: %s", e)


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
        if time.time() - mtime < EXCHANGE_INFO_TTL and "BTTCUSDT" in open(EXCHANGE_INFO_CACHE).read():
            with open(EXCHANGE_INFO_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)

    info = _get_client().get_exchange_info()
    with open(EXCHANGE_INFO_CACHE, "w", encoding="utf-8") as f:
        json.dump(info, f)
    return info


def get_exchange_info() -> Dict[str, object]:
    """Return exchange information directly from Binance without cache."""

    return _get_client().get_exchange_info()


def load_tradable_usdt_symbols() -> set[str]:
    """Return cached set of tradable symbols quoted in USDT."""

    global cached_usdt_pairs
    if cached_usdt_pairs:
        return cached_usdt_pairs
    info = get_exchange_info()
    pairs = [
        s.get('symbol')
        for s in info.get("symbols", [])
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    ]
    cached_usdt_pairs = {p.replace("USDT", "") for p in pairs}
    logger.debug("Loaded %d tradable USDT symbols", len(cached_usdt_pairs))
    return cached_usdt_pairs


def get_valid_symbols() -> list[str]:
    """Return list of tradable USDT pairs from Binance."""

    try:
        info = _get_client().get_exchange_info()
    except Exception as exc:  # pragma: no cover - network errors
        logger.error(
            "%s Не вдалося отримати exchange info: %s", TELEGRAM_LOG_PREFIX, exc
        )
        return []

    return [
        s["symbol"]
        for s in info.get("symbols", [])
        if (
            s.get("status") == "TRADING"
            and s.get("isSpotTradingAllowed")
            and s.get("quoteAsset") == "USDT"
        )
    ]


def get_valid_usdt_symbols() -> list[str]:
    """Return list of tradable USDT pairs from Binance."""

    symbols = get_valid_symbols()
    logger.info("[dev] Всього доступних USDT пар: %d", len(symbols))
    return symbols


def get_all_valid_symbols() -> list[str]:
    """Return list of all valid USDT trading pairs."""

    return [s for s in get_valid_usdt_symbols() if s.endswith("USDT") and is_symbol_valid(s)]

# NOTE: Loading trading pairs requires network access which is undesirable
# during automated testing. The call is now deferred until explicitly
# requested by the application.
refresh_valid_pairs()
logger.info("[init] VALID_PAIRS loaded: %d pairs", len(VALID_PAIRS))

# Preload exchange information for LOT_SIZE filters
try:
    data = get_exchange_info_cached()
    exchange_info = {s.get("symbol"): s for s in data.get("symbols", [])}
    logger.debug("[init] exchange_info loaded: %d symbols", len(exchange_info))
except Exception as exc:  # pragma: no cover - network errors
    logger.warning("[init] Failed to load exchange_info: %s", exc)


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

def get_account_info() -> Optional[Dict[str, object]]:
    """Return detailed account information using signed HTTP request."""

    url = f"{BINANCE_BASE_URL}/api/v3/account"
    params = sign_request({"timestamp": get_timestamp()})
    try:
        resp = _session.get(url, headers=get_headers(), params=params, timeout=10)
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

        if BINANCE_API_KEY and BINANCE_SECRET_KEY:
            logger.debug(
                f"[DEBUG] API: {BINANCE_API_KEY[:8]}..., SECRET: {BINANCE_SECRET_KEY[:8]}..."
            )
        else:
            logger.warning(
                "[ERROR] Binance ключі відсутні (None). Запуск можливий лише після налаштування config.py на сервері."
            )

        try:
            # Тестовий пінг до Binance
            if not BINANCE_TEST_MODE:
                temp_client.ping()
            logger.info("✅ Binance API доступний")

            account = temp_client.get_account()
            raw_balances = {
                asset.get('asset'): float(asset.get('free'))
                for asset in account.get('balances')
                if float(asset.get('free')) > 0
            }

            if not VALID_PAIRS:
                refresh_valid_pairs()

            balances: Dict[str, float] = {}
            for asset, amount in raw_balances.items():
                if asset in {"USDT", "BUSD"}:
                    balances[asset] = amount
                    continue

                pair = _to_usdt_pair(asset)
                if pair in VALID_PAIRS:
                    balances[asset] = amount

            return balances

        except BinanceAPIException as e:
            logger.error(f"📛 [BINANCE] Помилка при отриманні балансу: {e}")
            if e.code == -2015:
                logger.error(
                    "❌ Можливо: (1) ключ недійсний, (2) немає прав, (3) IP не в whitelist."
                )
            raise e

    except Exception as ex:  # pragma: no cover - diagnostics must not fail
        logger.exception("❗ Невідома помилка при ініціалізації Binance клієнта")
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

    if TEST_MODE:
        return 0.0

    try:
        bal = _get_client().get_asset_balance(asset="USDT")
        return float(bal.get("free", 0))
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("%s Помилка отримання балансу USDT: %s", TELEGRAM_LOG_PREFIX, exc)
        return 0.0


def get_token_balance(symbol: str) -> float:
    """Return available balance of specific token."""

    if TEST_MODE:
        return 0.0

    try:
        bal = _get_client().get_asset_balance(asset=symbol.upper())
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


def try_convert(symbol_from: str, symbol_to: str, amount: float) -> Optional[dict]:
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

        quote_id = data.get('quoteId')
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
        return {**result, "status": "success"}
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("❌ Помилка при конвертації %s: %s", symbol_from, exc)
        msg = str(exc)
        if "Signature for this request" in msg or "-1022" in msg:
            return {"status": "error", "message": "invalid_signature"}
        if symbol_to == "USDT":
            try:
                if _fallback_market_sell(symbol_from, amount):
                    return {"status": "market_sell"}
            except Exception as fallback_exc:  # pragma: no cover - network errors
                logger.warning(
                    "⚠️ Fallback market sell error for %s: %s",
                    symbol_from,
                    fallback_exc,
                )
        try:
            pair = f"{symbol_from}{symbol_to}"
            step_size = get_lot_step(pair)
            min_qty = get_min_qty(pair)
            min_notional = get_min_notional(pair)
            logger.warning(
                "[dev] Filter failure: minQty=%s, minNotional=%s, LOT_SIZE",
                min_qty,
                min_notional,
            )
        except Exception:
            pass
        msg = f"{symbol_from} \u2192 {symbol_to} не вдалося: {exc}"  # type: ignore[arg-type]
        logger.warning(msg)
        logger.warning("[dev] ❌ Binance повернув помилку, угода не відбулась: %s", msg)
        return {"status": "error", "message": str(exc)}


def convert_to_usdt(asset: str, amount: float):
    """Convert ``asset`` amount to USDT using Binance Convert API."""

    logger.info("🔁 Спроба конвертації %s %s в USDT", amount, asset)

    # Try client.convert_trade if available
    try:
        if hasattr(client, "convert_trade"):
            result = client.convert_trade(asset, "USDT", amount)
            if result.get("status") != "SUCCESS":
                raise Exception(f"Convert API повернув помилку: {result}")
            logger.info("✅ Конвертовано %s %s у USDT", amount, asset)
            return {**result, "status": "success"}
    except BinanceAPIException as exc:  # pragma: no cover - handle below
        msg = str(exc)
        if "Signature for this request" in msg or "-1022" in msg:
            logger.warning("[dev] ⛔ convert_trade недоступний: %s", exc)
            return {"status": "error", "message": "invalid_signature"}
        logger.warning("convert_trade fallback: %s", exc)
    except Exception as exc:  # pragma: no cover - handle below
        logger.warning("convert_trade fallback: %s", exc)

    return try_convert(asset, "USDT", amount)


def get_account_balances() -> Dict[str, Dict[str, str]]:
    """Return mapping of tradable assets to their free and locked amounts."""

    if not client:
        raise ValueError("[BINANCE] ❌ Binance client not initialized")

    try:
        account = client.get_account()
    except Exception as exc:  # pragma: no cover - network errors
        logger.error(
            "%s Не вдалося отримати баланси акаунта: %s", TELEGRAM_LOG_PREFIX, exc
        )
        return {}

    tradable = load_tradable_usdt_symbols()
    balances: Dict[str, Dict[str, str]] = {}

    for bal in account.get("balances", []):
        asset = bal.get("asset", "")
        free = float(bal.get("free", 0) or 0)
        locked = float(bal.get("locked", 0) or 0)
        total = free + locked
        if total <= 0:
            continue
        if asset == "USDT" or asset in tradable:
            balances[asset] = {"free": str(free), "locked": str(locked)}
        else:
            logger.debug("[dev] ⏭️ Пропущено %s: не торгується", asset)

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


def get_symbol_price(pair: str) -> float:
    """Return current price for ``pair`` quoted in USDT."""

    url = f"{BINANCE_BASE_URL}/api/v3/ticker/price"
    params = {"symbol": pair}
    try:
        resp = _session.get(url, params=params, timeout=(3, 5))
        resp.raise_for_status()
        return float(resp.json().get("price"))
    except Exception as e:
        if pair not in VALID_PAIRS:
            logger.warning(f"[dev] ⛔ {pair} не знайдено в VALID_PAIRS")
        logger.warning(f"[dev] ⚠️ Request failed in get_symbol_price: {e}")
        return 0.0


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


def place_market_order(
    symbol: str, side: str, amount: float, *, quantity: float | None = None
) -> Optional[Dict[str, object]]:
    """Place a market order for ``symbol`` on Binance."""

    if TEST_MODE:
        return {"symbol": symbol, "side": side, "amount": amount}

    base = normalize_symbol(symbol)
    pair = f"{base}USDT".upper()
    if pair not in VALID_PAIRS:
        logger.warning("⚠️ %s не знайдено у VALID_PAIRS, оновлюємо...", pair)
        refresh_valid_pairs()
        if pair not in VALID_PAIRS:
            logger.warning("⚠️ Після оновлення %s все ще не знайдено", pair)
            return None
    try:
        price = get_symbol_price(pair)
        step_size = get_lot_step(pair)
        if side.upper() == "BUY":
            if quantity is not None:
                logger.debug(
                    "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
                    float(quantity),
                    step_size,
                    price,
                )
                order = _get_client().create_order(
                    symbol=pair,
                    side=Client.SIDE_BUY,
                    type=Client.ORDER_TYPE_MARKET,
                    quantity=float(quantity),
                )
            else:
                qty_calc = amount / price if price else amount
                logger.debug(
                    "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
                    qty_calc,
                    step_size,
                    price,
                )
                order = _get_client().create_order(
                    symbol=pair,
                    side=Client.SIDE_BUY,
                    type=Client.ORDER_TYPE_MARKET,
                    quoteOrderQty=amount,
                )
        else:
            qty = adjust_qty_to_step(amount, step_size)
            logger.debug(
                "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
                qty,
                step_size,
                price,
            )
            order = _get_client().create_order(
                symbol=pair,
                side=Client.SIDE_SELL,
                type=Client.ORDER_TYPE_MARKET,
                quantity=float(qty),
            )
        logger.info("✅ Order placed: %s", order)
        return order
    except BinanceAPIException as e:
        logger.error("❌ Order error for %s: %s", pair, e)
        if "LOT_SIZE" in str(e):
            result = convert_to_usdt(base, amount)
            if result is None:
                logger.warning("[WARN] convert failed")
        return None
    except Exception as e:
        logger.error("❌ Order error for %s: %s", pair, e)
        return None


def market_buy_symbol_by_amount(symbol: str, amount: float) -> Dict[str, object]:
    """Buy ``symbol`` using market order for a specified USDT amount."""

    try:
        base = normalize_symbol(symbol)
        pair = f"{base}USDT".upper()
        if pair not in VALID_PAIRS:
            logger.warning("[dev] ⛔ %s не торгується", pair)
            return {"status": "error", "message": "invalid_symbol"}

        price = get_symbol_price(pair)
        if not price:
            logger.warning("[dev] ⛔ Price unavailable for %s", pair)
            return {"status": "error", "message": "no_price"}

        quantity = amount / price
        step_size = get_lot_step(pair)
        quantity = adjust_qty_to_step(quantity, step_size)
        logger.debug(
            "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
            quantity,
            step_size,
            price,
        )
        result = client.create_order(
            symbol=pair,
            side=SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
        )
        if result.get("status") != "FILLED":
            logger.warning("[dev] ❌ Ордер не виконано повністю: %s", result)
            return {"status": "error", "message": "Order not filled"}
        return {"status": "success", "message": "Filled"}
    except BinanceAPIException as e:  # pragma: no cover - network errors
        logger.warning("[dev] Binance buy error for %s: %s", pair, e)
        return {"status": "error", "message": str(e)}
    except Exception as exc:
        logger.warning("[dev] Unexpected buy error for %s: %s", pair, exc)
        return {"status": "error", "message": str(exc)}

def market_buy(symbol: str, usdt_amount: float) -> dict:
    """Ринкова купівля ``symbol`` на вказану суму в USDT."""

    try:
        logger.info(f"[dev] 🔼 Спроба купити {symbol} на {usdt_amount} USDT")
        pair = _to_usdt_pair(symbol)
        price_data = client.get_symbol_ticker(symbol=pair)
        current_price = float(price_data.get("price"))

        qty = usdt_amount / current_price
        step_size = get_lot_step(pair)
        min_qty = get_min_qty(pair)
        min_notional = get_min_notional(pair)
        qty_adj = adjust_qty_to_step(qty, step_size)
        logger.debug("[dev] 🧮 qty=%s step=%s adjusted=%s", qty, step_size, qty_adj)
        notional = qty_adj * current_price
        if qty_adj < min_qty or notional < min_notional:
            logger.warning(
                "[dev] ❌ Покупка відхилена: qty=%.8f, min_qty=%.8f, notional=%.8f, min_notional=%.8f — символ %s",
                qty_adj,
                min_qty,
                notional,
                min_notional,
                pair,
            )
            return {"status": "error", "message": "qty below min_qty"}

        logger.info(
            "[dev] Кориговано qty для %s: з %s → %s (stepSize: %s)",
            pair,
            qty,
            qty_adj,
            step_size,
        )

        for _ in range(10):
            try:
                order = place_market_order(symbol, "BUY", usdt_amount, quantity=float(qty_adj))
                if order and isinstance(order, dict) and order.get("status") in {"FILLED", "PARTIALLY_FILLED", "NEW"}:
                    return {**order, "status": "success"}
                if order and not isinstance(order, dict):
                    return order
            except BinanceAPIException as e:
                if "LOT_SIZE" in str(e):
                    qty_adj = adjust_qty_to_step(qty_adj - float(step_size), step_size)
                    if qty_adj < min_qty or qty_adj <= 0:
                        break
                    continue
                logger.error("❌ Помилка при ринковій купівлі %s: %s", symbol, e)
                return {"status": "error", "message": str(e)}
        logger.warning(
            "[dev] ❌ Binance LOT_SIZE: qty=%s, step=%s, min_qty=%s — не вдалося",
            qty_adj,
            step_size,
            min_qty,
        )
        return {"status": "error", "message": "LOT_SIZE filter failure"}

    except BinanceAPIException as e:
        logger.error("❌ Помилка при ринковій купівлі %s: %s", symbol, e)
        return {"status": "error", "message": str(e)}


def market_sell(symbol: str, quantity: float) -> dict:
    """Виконує ринковий продаж криптовалюти на вказану кількість."""

    try:
        step_size = get_lot_step(symbol)
        min_qty = get_min_qty(symbol)
        price = get_symbol_price(symbol)
        qty = adjust_qty_to_step(quantity, step_size)
        min_notional = get_min_notional(symbol)
        notional = qty * price

        if qty < min_qty or qty == 0 or notional < min_notional:
            logger.warning(
                "[dev] ❌ Покупка відхилена: qty=%.8f, min_qty=%.8f, notional=%.8f, min_notional=%.8f — символ %s",
                qty,
                min_qty,
                notional,
                min_notional,
                symbol,
            )
            return {"status": "error", "message": "qty below min_qty"}

        for _ in range(10):
            try:
                order = client.order_market_sell(symbol=symbol, quantity=float(qty))
                logger.info("✅ Продано %s %s", qty, symbol)
                return {**order, "status": "success"}
            except BinanceAPIException as e:
                if "LOT_SIZE" in str(e):
                    qty = adjust_qty_to_step(qty - float(step_size), step_size)
                    if qty < min_qty or qty <= 0:
                        break
                    continue
                logger.error("❌ Помилка при продажі %s: %s", symbol, e)
                return {"status": "error", "message": str(e)}

        logger.warning(
            "[dev] ❌ Binance LOT_SIZE: qty=%s, step=%s, min_qty=%s — не вдалося",
            qty,
            step_size,
            min_qty,
        )
        return {"status": "error", "message": "LOT_SIZE filter failure"}
    except BinanceAPIException as e:
        logger.error("❌ Помилка при продажі %s: %s", symbol, e)
        return {"status": "error", "message": str(e)}


def sell_asset(symbol: str, quantity: float) -> dict:
    """Sell ``symbol`` with fallback to ``_fallback_market_sell`` on failure."""

    step_size = get_lot_step(symbol)
    step = Decimal(str(step_size))
    adjusted_amount = (Decimal(str(quantity)) // step) * step
    adjusted_amount = adjusted_amount.quantize(step, rounding=decimal.ROUND_DOWN)

    logger.info(
        f"[dev] ⚙️ Округлена кількість {symbol}: {adjusted_amount} (step={step_size})"
    )

    order = place_market_order(symbol, "SELL", adjusted_amount)
    if order:
        return {"status": "market_order"}

    price = get_symbol_price(_to_usdt_pair(symbol))
    logger.warning(
        f"[dev] ⚠️ Неможливо продати {symbol} — minNotional або minQty не виконано: кількість={adjusted_amount}, ціна={price}"
    )

    success = _fallback_market_sell(symbol, adjusted_amount)
    if success:
        return {"status": "fallback_sell"}

    logger.error(
        f"[dev] ❌ Fallback market_sell також не вдався: {symbol}, кількість={adjusted_amount}"
    )
    return {"status": "failed"}

def place_sell_order(symbol: str, quantity: float, price: float) -> bool:
    """Place a limit sell order on Binance."""

    try:
        pair = _to_usdt_pair(symbol)
        step_size = get_lot_step(pair)
        qty = adjust_qty_to_step(quantity, step_size)
        logger.debug(
            "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
            qty,
            step_size,
            price,
        )
        order = client.create_order(
            symbol=pair,
            side="SELL",
            type="LIMIT",
            timeInForce="GTC",
            quantity=qty,
            price=str(round(price, 5)),
        )
        return True
    except Exception as e:  # pragma: no cover - network errors
        logger.error("Failed to place take profit order for %s: %s", symbol, e)
        return False


def place_limit_sell(symbol: str, quantity: float) -> dict:
    """Place a LIMIT sell order at current market price."""
    pair = _to_usdt_pair(symbol)
    price = get_symbol_price(pair)
    try:
        step_size = get_lot_step(pair)
        qty = adjust_qty_to_step(quantity, step_size)
        logger.debug(
            "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
            qty,
            step_size,
            price,
        )
        order = client.create_order(
            symbol=pair,
            side="SELL",
            type="LIMIT",
            timeInForce="GTC",
            quantity=qty,
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
        step_size = get_lot_step(symbol)
        qty = adjust_qty_to_step(quantity, step_size)
        logger.debug(
            "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
            qty,
            step_size,
            take_profit_price,
        )
        response = client.create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type=ORDER_TYPE_LIMIT,
            quantity=qty,
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
        step_size = get_lot_step(symbol)
        qty = adjust_qty_to_step(quantity, step_size)
        quantity_str = f"{qty:.8f}".rstrip("0").rstrip(".")
        logger.debug(
            "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
            qty,
            step_size,
            target_price,
        )
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
        step_size = get_lot_step(pair)
        qty = adjust_qty_to_step(quantity, step_size)
        logger.debug(
            "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
            qty,
            step_size,
            limit_price,
        )
        order = client.create_order(
            symbol=pair,
            side="BUY",
            type="STOP_LOSS_LIMIT",
            timeInForce="GTC",
            quantity=qty,
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
        step_size = get_lot_step(pair)
        qty = adjust_qty_to_step(quantity, step_size)
        logger.debug(
            "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
            qty,
            step_size,
            limit_price,
        )
        order = client.create_order(
            symbol=pair,
            side="SELL",
            type="STOP_LOSS_LIMIT",
            timeInForce="GTC",
            quantity=qty,
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
        step_size = get_lot_step(symbol)
        qty = adjust_qty_to_step(quantity, step_size)
        logger.debug(
            "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
            qty,
            step_size,
            stop_price,
        )
        order = client.create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type=ORDER_TYPE_STOP_LOSS_LIMIT,
            timeInForce=TIME_IN_FORCE_GTC,
            quantity=qty,
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
        resp = _session.get(url, headers=get_headers(), params=signed_params, timeout=10)
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
            cancel_order(int(o.get('orderId')), pair)


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

    token = TELEGRAM_TOKEN
    chat_id = ADMIN_CHAT_ID or CHAT_ID
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
        resp = _session.get(url, params={"symbol": pair}, timeout=5)
        resp.raise_for_status()
        return float(resp.json().get("price"))
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
            if s.get("symbol") == symbol:
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


def get_min_notional(symbol: str) -> float:
    """Return ``MIN_NOTIONAL`` value for trading ``symbol``."""
    try:
        data = get_exchange_info_cached()
        for s in data.get("symbols", []):
            if s.get("symbol") == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "MIN_NOTIONAL":
                        return float(f.get("minNotional"))
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning(
            "%s Помилка при отриманні MIN_NOTIONAL для %s: %s",
            TELEGRAM_LOG_PREFIX,
            symbol,
            exc,
        )
    return 0.0


def get_symbol_filters(symbol: str) -> list[dict]:
    """Return exchange filters for ``symbol``."""

    if symbol in exchange_info:
        return exchange_info[symbol].get("filters", [])
    try:
        info = _get_client().get_symbol_info(symbol)
        return info.get("filters", [])
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning("[dev] ❌ Не вдалося отримати фільтри для %s: %s", symbol, exc)
    return []


def get_lot_step(symbol: str) -> Decimal:
    """Return the stepSize for LOT_SIZE as Decimal."""

    info = client.get_symbol_info(symbol)
    for f in info.get("filters", []):
        if f.get("filterType") == "LOT_SIZE":
            return Decimal(f["stepSize"])
    raise ValueError(f"LOT_SIZE not found for {symbol}")


def get_min_qty(symbol: str) -> float:
    """Return ``LOT_SIZE`` minQty for ``symbol``."""

    try:
        info = client.get_symbol_info(symbol)
        for f in info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                return float(f["minQty"])
    except Exception as e:  # pragma: no cover - network errors
        logger.warning("[dev] ❌ Не вдалося отримати minQty для %s: %s", symbol, e)
    return 0.0


def get_min_quantity(symbol: str) -> float:
    """Return LOT_SIZE minQty for trading ``symbol``."""
    try:
        info = client.get_symbol_info(symbol)
        for f in info["filters"]:
            if f["filterType"] == "LOT_SIZE":
                return float(f["minQty"])
    except Exception as e:  # pragma: no cover - network errors
        logger.warning(
            "[dev] ❌ Не вдалося отримати minQty для %s: %s",
            symbol,
            e,
        )
    return 0.0


def _fallback_market_sell(asset: str, quantity: float) -> bool:
    """Attempt to sell ``asset`` to USDT market if possible."""
    pair = f"{asset.upper()}USDT"
    if pair not in VALID_PAIRS:
        return False

    price = get_symbol_price(pair)
    if price is None:
        return False

    min_notional = get_min_notional(pair)
    min_qty = get_min_qty(pair)
    step_size = get_lot_step(pair)
    step = Decimal(str(step_size))
    qty = (Decimal(str(quantity)) // step) * step
    qty = qty.quantize(step, rounding=decimal.ROUND_DOWN)
    if qty <= 0:
        logger.warning(
            "[dev] ❌ Покупка відхилена: qty=%.8f, min_qty=%.8f, notional=%.8f, min_notional=%.8f — символ %s",
            float(qty),
            min_qty,
            float(qty) * price,
            min_notional,
            pair,
        )
        return False

    notional = qty * price
    if notional < min_notional:
        logger.warning(
            "[dev] ❌ Покупка відхилена: qty=%.8f, min_qty=%.8f, notional=%.8f, min_notional=%.8f — символ %s",
            float(qty),
            min_qty,
            notional,
            min_notional,
            pair,
        )
        return False

    try:
        order = client.order_market_sell(symbol=pair, quantity=qty)
        logger.info("✅ Fallback market sell %s %s", qty, pair)
        return "orderId" in order
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning("⚠️ Fallback market sell failed for %s: %s", pair, exc)
        return False


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
        resp = _session.get(url, timeout=5)
        resp.raise_for_status()
        return float(resp.json().get("price"))
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
        resp = _session.get(url, params=params, timeout=5)
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


def get_whale_alert(symbol: str, threshold: float = 100_000) -> bool:
    """Return True if order book contains a single order over ``threshold`` USDT."""

    try:
        order_book = _get_client().get_order_book(symbol=symbol, limit=100)
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])
        max_bid = max([float(qty) * float(price) for price, qty in bids], default=0)
        max_ask = max([float(qty) * float(price) for price, qty in asks], default=0)
        return max_bid > threshold or max_ask > threshold
    except Exception as e:  # pragma: no cover - network errors
        logger.warning(f"[dev] Whale-check error for {symbol}: {e}")
        return False


def get_candlestick_klines(symbol: str, interval: str = "1h", limit: int = 100) -> List[List[float]]:
    """Return raw candlestick klines for a symbol."""
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    pair = _to_usdt_pair(symbol)
    assert not pair.endswith("USDTUSDT"), f"Invalid pair {pair}"
    logger.debug("get_candlestick_klines: %s -> %s", symbol, pair)
    params = {"symbol": pair, "interval": interval, "limit": limit}
    try:
        response = _session.get(url, params=params, timeout=(3, 5))
        response.raise_for_status()
        return response.json()
    except Exception as e:  # pragma: no cover - network errors
        logger.warning(f"[dev] ⚠️ Request failed in get_candlestick_klines: {e}")
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
        asset = pos.get('asset')
        amount = float(pos.get("free", 0))
        if amount == 0 or asset == "USDT":
            continue

        try:
            pair = _to_usdt_pair(asset)
            trades = client.get_my_trades(symbol=pair, limit=5)
            if not trades:
                continue

            total_cost = sum(float(t.get('price')) * float(t.get('qty')) for t in trades)
            total_qty = sum(float(t.get('qty')) for t in trades)

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
            s.get('baseAsset')
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
        resp = _session.get(url, timeout=10)
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
            symbol = item.get('symbol').replace("USDT", "")
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


def get_top_symbols_by_volume(limit: int = 60) -> list[str]:
    """Return top symbols by 24h quote volume."""

    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        response = requests.get(url, timeout=(3, 5))
        data = response.json()
        filtered = [
            item.get('symbol')
            for item in data
            if item.get('symbol').endswith("USDT")
            and not item.get('symbol').startswith(("USD", "BUSD", "TUSD"))
        ]
        sorted_pairs = sorted(
            filtered,
            key=lambda s: next(
                (float(i.get('quoteVolume')) for i in data if i.get("symbol") == s), 0
            ),
            reverse=True,
        )
        return [s.replace("USDT", "") for s in sorted_pairs[:limit]]
    except Exception as e:  # pragma: no cover - network errors
        logger.warning(f"[dev] ⚠️ Failed to fetch top symbols: {e}")
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
            tokens.append(asset.get('asset'))

    return tokens


if __name__ == "__main__":
    setup_logging()
    logger.info("🔧 Binance API модуль запущено напряму.")
    logger.info("➡️ Поточний портфель:")
    for asset, value in get_current_portfolio().items():
        logger.info("• %s: $%.2f", asset, value)


def place_limit_sell_order(symbol: str, quantity: float, price: float) -> dict:
    """
    Виставляє лімітний ордер на продаж з ціною Take Profit.
    """
    try:
        step_size = get_lot_step(symbol)
        qty = adjust_qty_to_step(quantity, step_size)
        logger.debug(
            "[dev] 🧪 Перевірка перед create_order: qty=%.8f, step_size=%.8f, price=%.8f",
            qty,
            step_size,
            price,
        )
        response = client.create_order(
            symbol=symbol,
            side=Client.SIDE_SELL,
            type=Client.ORDER_TYPE_LIMIT,
            timeInForce=Client.TIME_IN_FORCE_GTC,
            quantity=qty,
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
            quantity = balance * 0.99

        pair = _to_usdt_pair(symbol)
        step_size = get_lot_step(pair)
        qty = adjust_qty_to_step(quantity, step_size)
        params = {
            "symbol": pair,
            "side": "SELL",
            "type": "LIMIT",
            "quantity": qty,
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
            quantity = balance * 0.99

        pair = _to_usdt_pair(symbol)
        step_size = get_lot_step(pair)
        qty = adjust_qty_to_step(quantity, step_size)
        params = {
            "symbol": pair,
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "quantity": qty,
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


def buy_token_market(symbol: str, usdt_amount: float) -> dict:
    """Wrapper for ``market_buy`` with additional logging."""

    result = market_buy(symbol, usdt_amount)
    if result.get("status") != "success":
        logger.warning(
            "[dev] ❌ Binance повернув помилку, угода не відбулась: %s", result
        )
    return result


def get_candlestick_klines(symbol: str, interval: str = "1d", limit: int = 7):
    """Return candlestick klines for a tradable symbol with a short timeout."""

    base = normalize_symbol(symbol)
    if base not in load_tradable_usdt_symbols():
        raise ValueError(f"Token {base} не торгується на Binance")

    pair = _to_usdt_pair(symbol)
    assert not pair.endswith("USDTUSDT"), f"Invalid pair {pair}"
    logger.debug(
        "get_candlestick_klines(daily): %s -> %s interval=%s", symbol, pair, interval
    )

    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": pair, "interval": interval, "limit": limit}
    try:
        resp = _session.get(url, params=params, timeout=(3, 5))
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning(f"[dev] ⚠️ Request failed in get_candlestick_klines: {exc}")
        return []


def test_valid_pairs() -> None:
    """Log availability of some common USDT pairs."""

    test_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "XRPUSDT"]
    for symbol in test_symbols:
        if symbol not in VALID_PAIRS:
            logger.warning(f"❌ {symbol} — Немає в VALID_PAIRS!")
        else:
            logger.info(f"✅ {symbol} — OK")


def get_klines_safe(pair: str, interval: str = "1h", limit: int = 1000) -> list:
    """Безпечне отримання свічок — тільки якщо пара в VALID_PAIRS"""
    if pair not in VALID_PAIRS:
        logger.warning(f"[dev] ⚠️ Symbol {pair} not in VALID_PAIRS — skipping")
        return []
    try:
        return client.get_klines(symbol=pair, interval=interval, limit=limit)
    except Exception as e:  # pragma: no cover - network errors
        logger.warning(f"[dev] ⚠️ get_klines() failed for {pair}: {e}")
        return []


