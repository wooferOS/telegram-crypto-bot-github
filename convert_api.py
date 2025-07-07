import hmac
import hashlib
import logging
import time
from typing import Dict, List, Any

import requests

from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY
from utils_dev3 import get_current_timestamp

BASE_URL = "https://api.binance.com"

_session = requests.Session()
logger = logging.getLogger(__name__)


def _sign(params: Dict[str, Any]) -> Dict[str, Any]:
    params["timestamp"] = get_current_timestamp()
    query = "&".join(f"{k}={v}" for k, v in params.items())
    signature = hmac.new(BINANCE_SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature
    return params


def _headers() -> Dict[str, str]:
    return {"X-MBX-APIKEY": BINANCE_API_KEY}


def get_balances() -> Dict[str, float]:
    url = f"{BASE_URL}/api/v3/account"
    params = _sign({})
    resp = _session.get(url, params=params, headers=_headers(), timeout=10)
    data = resp.json()
    balances: Dict[str, float] = {}
    for bal in data.get("balances", []):
        total = float(bal.get("free", 0)) + float(bal.get("locked", 0))
        if total > 0:
            balances[bal["asset"]] = total
    return balances


def get_available_to_tokens(from_token: str) -> List[str]:
    url = f"{BASE_URL}/sapi/v1/convert/exchangeInfo"
    params = _sign({"fromAsset": from_token})
    resp = _session.get(url, params=params, headers=_headers(), timeout=10)
    data = resp.json()
    # Ensure compatibility with both list and dict responses
    if isinstance(data, list):
        data = {"toAssetList": data}
    return [item.get("toAsset") for item in data.get("toAssetList", [])]


def get_quote(from_token: str, to_token: str, amount: float) -> Dict[str, Any]:
    url = f"{BASE_URL}/sapi/v1/convert/getQuote"
    params = _sign({"fromAsset": from_token, "toAsset": to_token, "fromAmount": amount})
    resp = _session.post(url, params=params, headers=_headers(), timeout=10)
    return resp.json()


def accept_quote(quote_id: str) -> Dict[str, Any]:
    url = f"{BASE_URL}/sapi/v1/convert/acceptQuote"
    params = _sign({"quoteId": quote_id})
    resp = _session.post(url, params=params, headers=_headers(), timeout=10)
    return resp.json()
