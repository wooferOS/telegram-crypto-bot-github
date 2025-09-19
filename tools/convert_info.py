#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, time, hmac, hashlib, requests
from urllib.parse import urlencode
from pathlib import Path

# щоб бачив config_dev3.py в корені репо
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY

BASE = "https://api.binance.com"
TIMEOUT = 15
def now_ms(): return int(time.time()*1000)
def sign(qs: str) -> str: return hmac.new(BINANCE_SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()

def get(path: str, params: dict):
    p = dict(params); p.setdefault("recvWindow", 5000); p["timestamp"] = now_ms()
    qs = urlencode(p)
    return requests.get(BASE+path, params=qs+"&signature="+sign(qs),
                        headers={"X-MBX-APIKEY": BINANCE_API_KEY}, timeout=TIMEOUT)

def read_free(asset: str):
    r = get("/api/v3/account", {}); r.raise_for_status()
    for b in r.json().get("balances", []):
        if b.get("asset")==asset: return b.get("free","0")
    return "0"

def main():
    if len(sys.argv) < 3:
        print("USAGE: python3 tools/convert_info.py FROM_ASSET TO_ASSET [WALLET=SPOT|FUNDING]")
        sys.exit(1)
    fr, to = sys.argv[1].upper(), sys.argv[2].upper()
    wallet = (sys.argv[3].upper() if len(sys.argv)>3 else "SPOT")

    ei = get("/sapi/v1/convert/exchangeInfo", {"fromAsset": fr, "toAsset": to})
    print("[exchangeInfo]", ei.status_code, ei.text)
    print(f"[balance] {fr} free:", read_free(fr))
    print(f"[balance] {to} free:", read_free(to))
    print("[wallet]", wallet)

if __name__ == "__main__":
    main()
