#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, time, hmac, hashlib, requests
from urllib.parse import urlencode
from datetime import datetime, timezone
from pathlib import Path

# щоб бачив config_dev3.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY

BASE = "https://api.binance.com"
TIMEOUT = 20
def now_ms(): return int(time.time()*1000)
def sign(qs: str) -> str: return hmac.new(BINANCE_SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()
def _headers(): return {"X-MBX-APIKEY": BINANCE_API_KEY}

def get(path: str, params: dict):
    p = dict(params); p.setdefault("recvWindow", 5000); p["timestamp"] = now_ms()
    qs = urlencode(p)
    return requests.get(BASE+path, params=qs+"&signature="+sign(qs), headers=_headers(), timeout=TIMEOUT)

def order_status(oid: int):
    r = get("/sapi/v1/convert/orderStatus", {"orderId": oid})
    try: r.raise_for_status()
    except: return {}
    return r.json()

def fmt_ts(ms: int):
    try:
        return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except: return str(ms)

def main():
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    end = now_ms()
    start = end - hours*60*60*1000
    r = get("/sapi/v1/convert/tradeFlow", {"startTime": start, "endTime": end, "limit": 100})
    print("[tradeFlow]", r.status_code)
    if r.status_code != 200:
        print(r.text); sys.exit(1)

    lst = r.json().get("list", [])
    if not lst:
        print("(порожньо за останні", hours, "год)")
        return

    for it in lst:
        oid = it.get("orderId")
        st = order_status(oid) if oid else {}
        status = st.get("orderStatus") or it.get("status") or "UNKNOWN"
        side = st.get("side") or "-"
        ratio = st.get("ratio") or "-"
        inv   = st.get("inverseRatio") or "-"
        ctime = fmt_ts(st.get("createTime") or it.get("createTime") or end)

        print(f"- {ctime} | id={oid} | {it.get('fromAsset')}→{it.get('toAsset')} "
              f"{it.get('fromAmount')} → {it.get('toAmount')} | side={side} "
              f"| status={status} | ratio={ratio} | invRatio={inv}")

if __name__ == "__main__":
    main()
