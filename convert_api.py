import hmac
import time
import hashlib
import logging
from typing import Any, Dict, Optional

import requests

try:
    from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY
except Exception:  # pragma: no cover - optional keys for tests
    BINANCE_API_KEY = ""
    BINANCE_SECRET_KEY = ""

logger = logging.getLogger(__name__)

# ======= Константи Convert API =======
BASE_URL = "https://api.binance.com"
SAPI_PREFIX = "/sapi/v1/convert"

# Глобальні таймаути/ретраї для мережі
HTTP_TIMEOUT = 10
RETRY_COUNT = 2

# Ліміти опитування статусу ордера (імпортуються іншими модулями)
ORDER_POLL_MAX_SEC = 30
ORDER_POLL_INTERVAL = 2


# ======= Хелпери підпису запитів =======
def _ts() -> int:
    return int(time.time() * 1000)


def _sign(params: Dict[str, Any]) -> Dict[str, Any]:
    """Додає timestamp і підпис (HMAC SHA256) до params."""
    params = dict(params)
    params.setdefault("timestamp", _ts())
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    signature = hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"),
        qs.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    params["signature"] = signature
    return params


def _headers() -> Dict[str, str]:
    return {"X-MBX-APIKEY": BINANCE_API_KEY}


def _post(path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"{BASE_URL}{path}"
    last_err: Optional[str] = None
    for _ in range(RETRY_COUNT + 1):
        try:
            resp = requests.post(
                url, headers=_headers(), params=_sign(params), timeout=HTTP_TIMEOUT
            )
            if resp.status_code == 200:
                return resp.json()
            last_err = resp.text
        except Exception as e:  # pragma: no cover - network
            last_err = str(e)
        time.sleep(0.2)
    logger.warning("Convert POST %s failed: %s", path, last_err)
    return None


def _get(path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"{BASE_URL}{path}"
    last_err: Optional[str] = None
    for _ in range(RETRY_COUNT + 1):
        try:
            resp = requests.get(
                url, headers=_headers(), params=_sign(params), timeout=HTTP_TIMEOUT
            )
            if resp.status_code == 200:
                return resp.json()
            last_err = resp.text
        except Exception as e:  # pragma: no cover - network
            last_err = str(e)
        time.sleep(0.2)
    logger.warning("Convert GET %s failed: %s", path, last_err)
    return None


# ======= Публічні функції, які вже використовує код =======
def get_quote(from_token: str, to_token: str, amount: float) -> Optional[Dict[str, Any]]:
    """POST /sapi/v1/convert/getQuote"""
    if not from_token or not to_token or amount <= 0:
        return None
    payload = {
        "fromAsset": from_token,
        "toAsset": to_token,
        "fromAmount": f"{amount:.8f}",
    }
    data = _post(f"{SAPI_PREFIX}/getQuote", payload)
    if not isinstance(data, dict) or "quoteId" not in data:
        return None
    quote = {
        "quoteId": data.get("quoteId"),
        "ratio": float(data.get("ratio", 0)) or 0.0,
        "inverseRatio": float(data.get("inverseRatio", 0))
        or (
            1.0 / float(data.get("ratio", 0))
            if float(data.get("ratio", 0) or 0)
            else 0.0
        ),
        "fromAmount": float(data.get("fromAmount", 0)) or 0.0,
        "toAmount": float(data.get("toAmount", 0)) or 0.0,
        "validTime": data.get("validTime"),
        "fromAsset": data.get("fromAsset", from_token),
        "toAsset": data.get("toAsset", to_token),
    }
    return quote


def accept_quote(
    quote: Dict[str, Any],
    from_token: str,
    to_token: str,
) -> Optional[Dict[str, Any]]:
    """POST /sapi/v1/convert/acceptQuote"""
    if not isinstance(quote, dict):
        return None
    quote_id = quote.get("quoteId")
    if not quote_id:
        return None
    payload = {"quoteId": quote_id}
    data = _post(f"{SAPI_PREFIX}/acceptQuote", payload)
    if not isinstance(data, dict) or "orderId" not in data:
        return {
            "status": "error",
            "msg": data.get("msg") if isinstance(data, dict) else "acceptQuote failed",
        }
    resp = {
        "orderId": data.get("orderId"),
        "orderStatus": data.get("orderStatus", "PROCESS"),
        "status": "success" if data.get("orderStatus") == "SUCCESS" else "pending",
        "fromAmount": quote.get("fromAmount", 0.0),
        "toAmount": quote.get("toAmount", 0.0),
        "fromAsset": from_token,
        "toAsset": to_token,
    }
    return resp


def get_order_status(order_id: str) -> Optional[Dict[str, Any]]:
    """GET /sapi/v1/convert/orderStatus"""
    if not order_id:
        return None
    data = _get(f"{SAPI_PREFIX}/orderStatus", {"orderId": order_id})
    if not isinstance(data, dict) or "orderId" not in data:
        return None
    return {
        "orderId": data.get("orderId"),
        "orderStatus": data.get("orderStatus"),
        "status": "success"
        if data.get("orderStatus") == "SUCCESS"
        else "error"
        if data.get("orderStatus") in ("FAILED", "FAIL", "EXPIRED", "CANCELED")
        else "pending",
        "fromAmount": float(data.get("fromAmount", 0)) if data.get("fromAmount") else None,
        "toAmount": float(data.get("toAmount", 0)) if data.get("toAmount") else None,
        "fromAsset": data.get("fromAsset"),
        "toAsset": data.get("toAsset"),
    }


# === Інтерфейс, який використовує інший код ===
def sanitize_token_pair(from_token: str, to_token: str) -> str:
    if not from_token or not to_token:
        logger.warning("[dev3] ❌ Невірний токен: token=None під час symbol.upper()")
        return ""
    return f"{from_token.upper()}→{to_token.upper()}"


def get_balances() -> Dict[str, float]:
    data = _get("/api/v3/account", {})
    balances: Dict[str, float] = {}
    if isinstance(data, dict):
        for bal in data.get("balances", []):
            total = float(bal.get("free", 0)) + float(bal.get("locked", 0))
            if total > 0:
                asset = bal.get("asset")
                if asset:
                    balances[asset] = total
    return balances


def get_available_to_tokens(from_token: str) -> list[str]:
    data = _get(f"{SAPI_PREFIX}/exchangeInfo", {"fromAsset": from_token})
    if isinstance(data, list):
        data = {"toAssetList": data}
    return [item.get("toAsset") for item in data.get("toAssetList", [])]


def get_max_convert_amount(from_token: str, to_token: str) -> float:
    # Поточний ліміт Binance Convert фактично не обмежений через API
    return float("inf")
