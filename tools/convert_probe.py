import time, hmac, hashlib, requests, sys
from urllib.parse import urlencode
from pathlib import Path

# важливо: додати репозиторій у sys.path, щоб бачив config_dev3.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY

BASE = "https://api.binance.com"

def now_ms():
    return int(time.time()*1000)

def sign(qs: str) -> str:
    return hmac.new(BINANCE_SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()

def sreq(method, path, payload: dict, send_as_body=False, timeout=15):
    payload = dict(payload or {})
    payload.setdefault("recvWindow", 5000)
    payload["timestamp"] = now_ms()

    qs = urlencode(payload)
    sig = sign(qs)
    url = BASE + path
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}

    if method == "GET":
        return requests.get(url, params=qs + "&signature=" + sig, headers=headers, timeout=timeout)

    if send_as_body:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = qs + "&signature=" + sig
        return requests.post(url, data=body, headers=headers, timeout=timeout)

    return requests.post(url, params=qs + "&signature=" + sig, headers=headers, timeout=timeout)

def human(resp):
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, {"raw": resp.text[:400]}

def try_quote(fr, to, amount, wallet, send_as_body):
    r = sreq("POST", "/sapi/v1/convert/getQuote", {
        "fromAsset": fr, "toAsset": to, "fromAmount": str(amount), "walletType": wallet
    }, send_as_body=send_as_body)
    return human(r)

def try_accept(quote_id, wallet, send_as_body):
    r = sreq("POST", "/sapi/v1/convert/acceptQuote", {
        "quoteId": quote_id, "walletType": wallet
    }, send_as_body=send_as_body)
    return human(r)

def main():
    if len(sys.argv) < 4:
        print("USAGE: python3 tools/convert_probe.py FROM_ASSET TO_ASSET AMOUNT [WALLET=SPOT|FUNDING]")
        sys.exit(1)

    fr, to, amount = sys.argv[1], sys.argv[2], sys.argv[3]
    wallet = sys.argv[4] if len(sys.argv) > 4 else "SPOT"

    print(f"[I] Probing {fr}->{to} amount={amount} wallet={wallet}")

    # пробуємо і як query, і як x-www-form-urlencoded body
    for mode in ("query", "body"):
        send_as_body = (mode == "body")
        print(f"[I] getQuote mode={mode}")
        sc, body = try_quote(fr, to, amount, wallet, send_as_body)
        print("   status:", sc, "body:", body)

        if sc == 200 and isinstance(body, dict) and "quoteId" in body:
            qid = body["quoteId"]
            print("[I] quoteId:", qid, "-> trying acceptQuote…")
            sc2, body2 = try_accept(qid, wallet, send_as_body)
            print("   acceptQuote status:", sc2, "body:", body2)
            return

    print("[W] No quoteId obtained. Likely balance is insufficient for this wallet, or amount is below Convert minimum, or pair not supported by Convert.")

if __name__ == "__main__":
    main()
