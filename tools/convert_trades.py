#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time, hmac, hashlib, requests, sys
from urllib.parse import urlencode
from pathlib import Path

# щоб бачив config_dev3.py в корені репо
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY

BASE = "https://api.binance.com"
TIMEOUT = 20
def now_ms(): return int(time.time()*1000)
def sign(qs: str) -> str: return hmac.new(BINANCE_SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()
def get(path: str, params: dict):
    p = dict(params); p.setdefault("recvWindow", 5000); p["timestamp"] = now_ms()
    qs = urlencode(p)
    return requests.get(BASE+path, params=qs+"&signature="+sign(qs),
                        headers={"X-MBX-APIKEY": BINANCE_API_KEY}, timeout=TIMEOUT)
def main():
    end = now_ms()
    start = end - 24*60*60*1000  # останні 24 години
    r = get("/sapi/v1/convert/tradeFlow", {"startTime": start, "endTime": end, "limit": 100})
    print("[tradeFlow]", r.status_code)
    if r.status_code != 200:
        print(r.text); sys.exit(1)
    for it in r.json().get("list", []):
        print(f"- {it.get('orderId')} {it.get('fromAsset')}->{it.get('toAsset')} "
              f"{it.get('fromAmount')} -> {it.get('toAmount')} status={it.get('status')}")
if __name__ == "__main__":
    main()
