import time, hmac, hashlib, requests, json
from urllib.parse import urlencode
from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY

BASE = "https://api.binance.com"

def now_ms():
    return int(time.time() * 1000)

def sign(body: str) -> str:
    return hmac.new(BINANCE_SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()

def signed_req(method, path, payload: dict, send_as_body=False, headers_extra=None, timeout=15):
    payload = dict(payload or {})
    payload.setdefault("recvWindow", 5000)
    payload["timestamp"] = now_ms()

    qs = urlencode(payload)
    sig = sign(qs)
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    if headers_extra: headers.update(headers_extra)

    url = BASE + path
    if method == "GET":
        return requests.get(url, params=qs + "&signature=" + sig, headers=headers, timeout=timeout)
    if send_as_body:
        # Content-Type x-www-form-urlencoded, тіло = qs&signature=...
        body = qs + "&signature=" + sig
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        return requests.post(url, data=body, headers=headers, timeout=timeout)
    else:
        # сигнатуру в query
        return requests.post(url, params=qs + "&signature=" + sig, headers=headers, timeout=timeout)

def get_spot_usdt():
    r = signed_req("GET", "/api/v3/account", {}, send_as_body=False)
    try:
        data = r.json()
        for b in data.get("balances", []):
            if b["asset"] == "USDT":
                return float(b["free"]), float(b["locked"])
    except Exception:
        pass
    return None, None

def get_funding_usdt():
    # funding wallet: POST /sapi/v1/asset/get-funding-asset (signed)
    r = signed_req("POST", "/sapi/v1/asset/get-funding-asset", {}, send_as_body=True)
    try:
        arr = r.json()
        for it in arr:
            if it.get("asset") == "USDT":
                # fields vary (e.g. 'free', 'locked' or 'freeAmount'); try both
                free = float(it.get("free", it.get("freeAmount", 0.0)))
                locked = float(it.get("locked", it.get("lockedAmount", 0.0)))
                return free, locked
    except Exception:
        pass
    return None, None

def get_quote(from_asset, to_asset, from_amount, wallet_type="SPOT"):
    payload = {
        "fromAsset": from_asset,
        "toAsset": to_asset,
        "fromAmount": str(from_amount),
        "walletType": wallet_type,
        # за замовчуванням validTime = 10s, можна вказати: 10s, 30s, 1m
    }
    # Convert trade вимагає підпис і ключ, краще передавати у body
    return signed_req("POST", "/sapi/v1/convert/getQuote", payload, send_as_body=True)

def accept_quote(quote_id):
    return signed_req("POST", "/sapi/v1/convert/acceptQuote", {"quoteId": quote_id}, send_as_body=True)

if __name__ == "__main__":
    from_amount = 10   # змініть при потребі
    pair = ("USDT", "BTC")

    spot_free, spot_locked = get_spot_usdt()
    funding_free, funding_locked = get_funding_usdt()
    print(f"[BALANCE] SPOT USDT free={spot_free} locked={spot_locked}")
    print(f"[BALANCE] FUNDING USDT free={funding_free} locked={funding_locked}")

    # Оберіть гаманець з фактичним балансом: "SPOT" або "FUNDING" або комбінацію "SPOT_FUNDING"
    wallet_type = "SPOT" if (spot_free or 0) >= from_amount else ("FUNDING" if (funding_free or 0) >= from_amount else "SPOT")

    print(f"[QUOTE] Requesting {pair[0]}->{pair[1]} amount={from_amount} walletType={wallet_type}")
    rq = get_quote(pair[0], pair[1], from_amount, wallet_type=wallet_type)
    print("HTTP", rq.status_code)
    print("Body", rq.text[:500])

    try:
        data = rq.json()
    except Exception:
        data = {}

    qid = data.get("quoteId")
    if qid:
        print("[QUOTE] Got quoteId:", qid, " — accepting...")
        ra = accept_quote(qid)
        print("AcceptQuote HTTP", ra.status_code)
        print("AcceptQuote Body", ra.text[:500])
    else:
        print("[QUOTE] No quoteId (ймовірно, недостатньо коштів у вибраному walletType або сума нижча мінімуму).")
