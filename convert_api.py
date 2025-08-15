import hmac
import hashlib
import time
import logging
from urllib.parse import urlencode
from typing import Any, Dict, List

import requests

from utils_dev3 import BINANCE_BASE_URL, CONVERT_ENABLED, to_convert_asset

try:  # API credentials from config
    import config_dev3 as cfg

    API_KEY = cfg.BINANCE_API_KEY
    API_SECRET = cfg.BINANCE_API_SECRET
except Exception:  # pragma: no cover - optional config
    API_KEY = ""
    API_SECRET = ""

logger = logging.getLogger("dev3")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _signed_request(
    method: str, path: str, params: Dict[str, Any] | None = None, timeout: int = 20
) -> Dict[str, Any] | None:
    """Perform signed REST request to Binance.

    All parameters are placed into the query string; body is never sent.
    Errors are logged and result ``None`` is returned.
    """

    if not API_KEY or not API_SECRET:
        logger.error("[dev3] API ключі не налаштовані")
        return None
    params = {k: v for k, v in (params or {}).items() if v is not None}
    params.setdefault("recvWindow", 50000)
    params["timestamp"] = _now_ms()
    query = urlencode(params, doseq=True)
    signature = hmac.new(
        API_SECRET.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    url = f"{BINANCE_BASE_URL}{path}?{query}&signature={signature}"
    headers = {"X-MBX-APIKEY": API_KEY}
    try:
        resp = requests.request(method.upper(), url, headers=headers, timeout=timeout)
    except Exception as exc:  # pragma: no cover - network
        logger.error("Convert API network error: %s", exc)
        return None
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if resp.status_code != 200:
        logger.error(
            "Convert API error: status=%s code=%s msg=%s body=%s",
            resp.status_code,
            data.get("code"),
            data.get("msg"),
            data,
        )
        return None
    return data


# ---- exchangeInfo with 6h cache ----
_EXCHANGE_CACHE: Dict[str, Any] | None = None
_EXCHANGE_CACHE_TS = 0.0
_EXCHANGE_TTL = 6 * 60 * 60


def exchange_info() -> Dict[str, Any] | None:
    """Return cached exchangeInfo for Convert API."""

    global _EXCHANGE_CACHE, _EXCHANGE_CACHE_TS
    now = time.time()
    if _EXCHANGE_CACHE and now - _EXCHANGE_CACHE_TS < _EXCHANGE_TTL:
        return _EXCHANGE_CACHE
    data = _signed_request("GET", "/sapi/v1/convert/exchangeInfo")
    if not isinstance(data, dict):
        return None
    assets = data.get("assets") or data.get("assetInfo") or data.get("assetList") or []
    pairs_raw = (
        data.get("pairs")
        or data.get("symbols")
        or data.get("quotePairs")
        or data.get("fromAssetList")
        or []
    )
    pairs: List[Dict[str, Any]] = []
    if isinstance(pairs_raw, list):
        for p in pairs_raw:
            if not isinstance(p, dict):
                continue
            fa = p.get("fromAsset") or p.get("baseAsset") or p.get("from")
            ta = p.get("toAsset") or p.get("quoteAsset") or p.get("to")
            if fa and ta:
                item = dict(p)
                item["fromAsset"] = fa
                item["toAsset"] = ta
                pairs.append(item)
    result = {"assets": assets if isinstance(assets, list) else [], "pairs": pairs}
    _EXCHANGE_CACHE = result
    _EXCHANGE_CACHE_TS = now
    return result


def get_quote(
    from_asset: str,
    to_asset: str,
    from_amount: str | float,
    wallet_type: str = "SPOT",
) -> Dict[str, Any] | None:
    fa = to_convert_asset(from_asset)
    ta = to_convert_asset(to_asset)
    params = {
        "fromAsset": fa,
        "toAsset": ta,
        "fromAmount": str(from_amount),
        "walletType": wallet_type,
    }
    data = _signed_request("POST", "/sapi/v1/convert/getQuote", params)
    if not isinstance(data, dict):
        return None
    return {
        "ratio": float(data.get("ratio", 0) or 0.0),
        "inverseRatio": float(data.get("inverseRatio", 0) or 0.0),
        "validTimestamp": int(data.get("validTimestamp") or data.get("validTime") or 0),
        "toAmount": float(data.get("toAmount", 0) or 0.0),
        "fromAmount": float(data.get("fromAmount", 0) or 0.0),
        "quoteId": data.get("quoteId"),
        "fromAsset": fa,
        "toAsset": ta,
    }


def accept_quote(quote_id: str) -> Dict[str, Any] | None:
    if not quote_id:
        logger.warning("[dev3] accept_quote без quoteId")
        return None
    return _signed_request("POST", "/sapi/v1/convert/acceptQuote", {"quoteId": quote_id})


def accept_quote_old(quote: Dict[str, Any], from_token: str, to_token: str) -> Dict[str, Any] | None:
    """Legacy wrapper compatible with older code paths."""
    if not isinstance(quote, dict):
        return None
    qid = quote.get("quoteId")
    if not qid:
        return None
    resp = accept_quote(qid)
    if isinstance(resp, dict):
        resp.setdefault("fromAmount", quote.get("fromAmount"))
        resp.setdefault("toAmount", quote.get("toAmount"))
        resp.setdefault("fromAsset", from_token)
        resp.setdefault("toAsset", to_token)
    return resp


def _sync_time() -> None:  # legacy no-op
    return None


def get_balances(wallet: str = "SPOT") -> Dict[str, float]:
    """Return balances for specified wallet."""

    wallet = (wallet or "SPOT").upper()
    balances: Dict[str, float] = {}
    if wallet == "FUNDING":
        data = _signed_request("POST", "/sapi/v1/asset/get-funding-asset", {})
        rows = []
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("balances") or data.get("data") or data.get("assets") or []
        for r in rows:
            asset = r.get("asset")
            try:
                free = float(r.get("free", 0))
            except Exception:
                free = 0.0
            if asset and free > 0:
                balances[asset] = free
    else:
        data = _signed_request("GET", "/api/v3/account", {})
        if isinstance(data, dict):
            for b in data.get("balances", []):
                asset = b.get("asset")
                try:
                    free = float(b.get("free", 0))
                except Exception:
                    free = 0.0
                if asset and free > 0:
                    balances[asset] = free
    if not balances:
        logger.warning("[dev3] ⚠️ get_balances returned empty result for %s", wallet)
    return balances


def get_available_to_tokens(from_asset: str) -> List[str]:
    info = exchange_info()
    if not info:
        return []
    fa = (from_asset or "").strip().upper()
    out: List[str] = []
    for p in info.get("pairs", []):
        if isinstance(p, dict) and p.get("fromAsset") == fa:
            ta = p.get("toAsset")
            if isinstance(ta, str):
                out.append(ta)
    return out


def sanitize_token_pair(a: str, b: str) -> tuple[str, str]:
    aa = (a or "").strip().upper()
    bb = (b or "").strip().upper()
    if not aa or not bb or aa == bb:
        return "", ""
    return aa, bb


# --- Optional helpers for order status polling ---
ORDER_POLL_MAX_SEC = 30
ORDER_POLL_INTERVAL = 2


def get_order_status(order_id: str) -> Dict[str, Any] | None:
    if not order_id:
        return None
    return _signed_request(
        "GET", "/sapi/v1/convert/orderStatus", {"orderId": order_id}
    )

