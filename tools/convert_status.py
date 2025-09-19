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
def sign(qs: str) -> str:
    return hmac.new(BINANCE_SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()

def get(path: str, params: dict):
    p = dict(params)
    p.setdefault("recvWindow", 5000)
    p["timestamp"] = now_ms()
    qs = urlencode(p)
    return requests.get(
        BASE + path,
        params=qs + "&signature=" + sign(qs),
        headers={"X-MBX-APIKEY": BINANCE_API_KEY},
        timeout=TIMEOUT,
    )

def main():
    if len(sys.argv) < 2:
        print("USAGE: python3 tools/convert_status.py ORDER_ID [--wait SECONDS]")
        sys.exit(1)

    order_id = sys.argv[1]
    wait = 0
    if len(sys.argv) >= 4 and sys.argv[2] == "--wait":
        try:
            wait = int(sys.argv[3])
        except: pass

    deadline = time.time() + wait
    while True:
        r = get("/sapi/v1/convert/orderStatus", {"orderId": order_id})
        print("[orderStatus]", r.status_code, r.text)
        if r.status_code != 200:
            sys.exit(2)
        data = r.json()
        st = (data.get("orderStatus") or "").upper()
        if st in ("SUCCESS", "COMPLETED", "FAILED", "CANCELED"):
            # SUCCESS/COMPLETED — ок, FAILED/CANCELED — не ок
            sys.exit(0 if st in ("SUCCESS", "COMPLETED") else 3)
        if time.time() >= deadline or wait == 0:
            break
        time.sleep(1)

if __name__ == "__main__":
    main()
