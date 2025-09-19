#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, time, hmac, hashlib, requests
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN, InvalidOperation, getcontext
from pathlib import Path

# щоб бачив config_dev3.py в корені репо
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY

BASE = "https://api.binance.com"
TIMEOUT = 20
getcontext().prec = 40

def now_ms(): return int(time.time()*1000)
def sign(qs: str) -> str: return hmac.new(BINANCE_SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()

def post(path: str, params: dict):
    p = dict(params); p.setdefault("recvWindow", 5000); p["timestamp"] = now_ms()
    qs = urlencode(p); body = qs + "&signature=" + sign(qs)
    return requests.post(BASE+path, data=body,
        headers={"X-MBX-APIKEY": BINANCE_API_KEY, "Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT)

def get(path: str, params: dict):
    p = dict(params); p.setdefault("recvWindow", 5000); p["timestamp"] = now_ms()
    qs = urlencode(p)
    return requests.get(BASE+path, params=qs+"&signature="+sign(qs),
        headers={"X-MBX-APIKEY": BINANCE_API_KEY}, timeout=TIMEOUT)

def floor_str_8(x: Decimal) -> str:
    q = x.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    s = format(q, "f")
    if "." in s: s = s.rstrip("0").rstrip(".")
    return s if s else "0"

def read_free_balance(asset: str) -> Decimal:
    r = get("/api/v3/account", {}); r.raise_for_status()
    data = r.json()
    for b in data.get("balances", []):
        if b.get("asset")==asset:
            try: return Decimal(b.get("free","0"))
            except InvalidOperation: return Decimal(0)
    return Decimal(0)

def main():
    if len(sys.argv) < 4:
        print("USAGE: python3 tools/convert_quote.py FROM_ASSET TO_ASSET AMOUNT [WALLET=SPOT|FUNDING]")
        sys.exit(1)

    fr, to, amount = sys.argv[1].upper(), sys.argv[2].upper(), sys.argv[3]
    wallet = (sys.argv[4].upper() if len(sys.argv)>4 else "SPOT")

    ei_resp = get("/sapi/v1/convert/exchangeInfo", {"fromAsset": fr, "toAsset": to})
    if ei_resp.status_code != 200:
        print("[exchangeInfo]", ei_resp.status_code, ei_resp.text); sys.exit(2)
    ei_list = ei_resp.json()
    if not isinstance(ei_list, list) or not ei_list:
        print("[exchangeInfo] unexpected:", ei_list); sys.exit(2)
    ei = ei_list[0]
    print("[exchangeInfo]", ei)

    if str(amount).upper() == "ALL":
        amount_dec = read_free_balance(fr)
        print(f"[amount=ALL] {fr} free =", floor_str_8(amount_dec))
    else:
        try: amount_dec = Decimal(str(amount))
        except InvalidOperation:
            print(f"[!] Invalid amount: {amount}"); sys.exit(3)

    from_min = Decimal(ei.get("fromAssetMinAmount","0"))
    from_max = Decimal(ei.get("fromAssetMaxAmount","0"))
    if from_max > 0 and amount_dec > from_max: amount_dec = from_max
    amount_dec = amount_dec.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    if amount_dec < from_min:
        print(f"[!] Amount {floor_str_8(amount_dec)} < min {from_min}. Спробуйте >= {from_min}"); sys.exit(4)
    if amount_dec <= 0:
        print("[!] Amount after rounding is 0"); sys.exit(8)
    amount_str = floor_str_8(amount_dec)

    q = {"fromAsset": fr, "toAsset": to, "fromAmount": amount_str, "walletType": wallet}
    r = post("/sapi/v1/convert/getQuote", q)
    print("[getQuote]", r.status_code, r.text)
    if r.status_code != 200: sys.exit(5)

if __name__ == "__main__":
    main()
