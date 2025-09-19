#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, time, hmac, hashlib, requests, os
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN, InvalidOperation, getcontext
from pathlib import Path
import argparse

# щоб бачив config_dev3.py в корені репо
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY

BASE = "https://api.binance.com"
TIMEOUT = 20
getcontext().prec = 40

def now_ms() -> int:
    return int(time.time() * 1000)

def sign(qs: str) -> str:
    return hmac.new(BINANCE_SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()

def _headers():
    return {"X-MBX-APIKEY": BINANCE_API_KEY}

def _do_request(method: str, path: str, payload: dict, is_post_body: bool):
    """Єдиний відправник запитів із 1 ретраєм на -1021 (timestamp)."""
    p = dict(payload)
    p.setdefault("recvWindow", 5000)
    p["timestamp"] = now_ms()
    qs = urlencode(p)
    url = BASE + path

    def _send(qs_local: str):
        if method == "GET":
            return requests.get(
                url, params=qs_local + "&signature=" + sign(qs_local),
                headers=_headers(), timeout=TIMEOUT
            )
        body = qs_local + "&signature=" + sign(qs_local)
        return requests.post(
            url,
            data=(body if is_post_body else None),
            params=(None if is_post_body else body),
            headers={**_headers(), "Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT
        )

    r = _send(qs)
    try:
        j = r.json()
    except Exception:
        j = {}
    if (r.status_code in (400, 401, 418) or r.status_code >= 500) and isinstance(j, dict) and str(j.get("code")) == "-1021":
        time.sleep(0.5)
        p["timestamp"] = now_ms()
        qs2 = urlencode(p)
        r = _send(qs2)
    return r

def post(path: str, params: dict):
    return _do_request("POST", path, params, is_post_body=True)

def get(path: str, params: dict):
    return _do_request("GET", path, params, is_post_body=False)

def floor_str_8(x: Decimal) -> str:
    """Обрізати (ROUND_DOWN) до максимум 8 знаків після крапки і прибрати хвости нулів."""
    q = x.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"
    url = BASE + path

    def _send(qs_local: str):
        if method == "GET":
            return requests.get(
                url,
                params=qs_local + "&signature=" + sign(qs_local),
                headers=_headers(),
                timeout=TIMEOUT,
            )
        body = qs_local + "&signature=" + sign(qs_local)
        return requests.post(
            url,
            data=(body if is_post_body else None),
            params=(None if is_post_body else body),
            headers={**_headers(), "Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT,
        )

    r = _send(qs)
    try:
        j = r.json()
    except Exception:
        j = {}
    if isinstance(j, dict) and str(j.get("code")) == "-1021":
        # Timestamp for this request is outside of the recvWindow.
        time.sleep(0.5)
        p["timestamp"] = now_ms()
        qs2 = urlencode(p)
        r = _send(qs2)
    return r

def post(path: str, params: dict):
    return _do_request("POST", path, params, is_post_body=True)

def get(path: str, params: dict):
    return _do_request("GET", path, params, is_post_body=False)

def floor_str_8(x: Decimal) -> str:
    """Обрізати (ROUND_DOWN) до максимум 8 знаків після крапки і прибрати хвости нулів."""
    q = x.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"

def read_free_balance(asset: str) -> Decimal:
    """SPOT баланс (free)."""
    r = get("/api/v3/account", {})
    r.raise_for_status()
    data = r.json()
    for b in data.get("balances", []):
        if b.get("asset") == asset:
            try:
                return Decimal(b.get("free", "0"))
            except InvalidOperation:
                return Decimal(0)
    return Decimal(0)

def read_free_funding(asset: str) -> Decimal:
    """FUNDING баланс (free) через /sapi/v3/asset/getUserAsset."""
    r = post("/sapi/v3/asset/getUserAsset", {"needBtcValuation": False})
    try:
        r.raise_for_status()
        arr = r.json()
        for it in arr:
            if it.get("asset") == asset:
                try:
                    return Decimal(it.get("free", "0"))
                except InvalidOperation:
                    return Decimal(0)
    except Exception:
        return Decimal(0)
    return Decimal(0)

def read_free_by_wallet(asset: str, wallet: str) -> Decimal:
    return read_free_funding(asset) if (wallet or "").upper() == "FUNDING" else read_free_balance(asset)
    return _do_request("GET", path, params, is_post_body=False)

def floor_str_8(x: Decimal) -> str:
    """Обрізати (ROUND_DOWN) до максимум 8 знаків після крапки і прибрати хвости нулів."""
    q = x.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"

def main():
    ap = argparse.ArgumentParser(description="Convert NOW via Binance Convert API")
    ap.add_argument("from_asset")
    ap.add_argument("to_asset")
    ap.add_argument("amount", help='число або "ALL"')
    ap.add_argument("wallet", nargs="?", default="SPOT", choices=["SPOT", "FUNDING"])
    ap.add_argument("--info", action="store_true", help="показати min/max і баланси SPOT/FUNDING та вийти")
    ap.add_argument("--dry-run", action="store_true", help="лише котирування без угоди")
    args = ap.parse_args()

    fr = args.from_asset.upper()
    to = args.to_asset.upper()
    wallet = args.wallet.upper()
    DRY = args.dry_run or (os.environ.get("DRY_RUN") == "1")

    # 1) exchangeInfo — мін/макс
    ei_resp = get("/sapi/v1/convert/exchangeInfo", {"fromAsset": fr, "toAsset": to})
    if ei_resp.status_code != 200:
        print("[exchangeInfo]", ei_resp.status_code, ei_resp.text)
        sys.exit(2)
    ei_list = ei_resp.json()
    if not isinstance(ei_list, list) or not ei_list:
        print("[exchangeInfo] unexpected:", ei_list)
        sys.exit(2)
    ei = ei_list[0]
    print("[exchangeInfo]", ei)

    # --info режим: просто показати ліміти та баланси і вийти
    if args.info:
        from_spot = read_free_balance(fr)
        to_spot   = read_free_balance(to)
        try:
            from_fund = read_free_funding(fr)
            to_fund   = read_free_funding(to)
        except Exception:
            from_fund = to_fund = Decimal(0)
        print("[info] FROM:", fr, "min=", ei.get("fromAssetMinAmount"), "max=", ei.get("fromAssetMaxAmount"))
        print("[info] TO  :", to, "min=", ei.get("toAssetMinAmount"),   "max=", ei.get("toAssetMaxAmount"))
        print(f"[balance] {fr} SPOT   =", floor_str_8(from_spot))
        print(f"[balance] {fr} FUNDING=", floor_str_8(from_fund))
        print(f"[balance] {to} SPOT   =", floor_str_8(to_spot))
        print(f"[balance] {to} FUNDING=", floor_str_8(to_fund))
        sys.exit(0)

    # 2) AMOUNT=ALL → беремо free з потрібного гаманця
    if str(args.amount).upper() == "ALL":
        amount_dec = read_free_by_wallet(fr, wallet)
        print(f"[amount=ALL] {fr} free =", floor_str_8(amount_dec))
    else:
        try:
            amount_dec = Decimal(str(args.amount))
        except InvalidOperation:
            print(f"[!] Invalid amount: {args.amount}")
            sys.exit(3)

    # Показати реальний вільний баланс і не лізти в acceptQuote, якщо його не вистачає
    free_dec = read_free_by_wallet(fr, wallet)
    print(f"[balance] {fr} free ({wallet}) =", floor_str_8(free_dec))
    if amount_dec > free_dec:
        print(f"[!] Requested {floor_str_8(amount_dec)} {fr} > free {floor_str_8(free_dec)}. Зменшіть суму або поповніть баланс.")
        if not DRY:
            sys.exit(9)
        else:
            print("[dry-run] Продовжуємо тільки для попереднього котирування…")

    # 3) Застосувати min/max і обрізання до 8 знаків (ROUND_DOWN)
    from_min = Decimal(ei.get("fromAssetMinAmount", "0"))
    from_max = Decimal(ei.get("fromAssetMaxAmount", "0"))
    if from_max > 0 and amount_dec > from_max:
        print(f"[!] Amount {floor_str_8(amount_dec)} > max {from_max}")
        sys.exit(4)
    if amount_dec < from_min:
        print(f"[!] Amount {floor_str_8(amount_dec)} < min {from_min}. Спробуйте >={from_min}")
        sys.exit(4)
    amount_str = floor_str_8(amount_dec)

    # 4) getQuote
    q_resp = post("/sapi/v1/convert/getQuote", {
        "fromAsset": fr,
        "toAsset": to,
        "fromAmount": amount_str,
        "walletType": wallet,
    })
    try:
        print("[getQuote]", q_resp.status_code, q_resp.text)
        q_js = q_resp.json()
    except Exception:
        q_js = {}
    if q_resp.status_code != 200 or "quoteId" not in q_js:
        print("[!] No quoteId — перевір баланс/мінімум/пару/гаманець.")
        sys.exit(5)

    if DRY:
        print("[dry-run] skipping acceptQuote")
        sys.exit(0)

    # 5) acceptQuote
    a_resp = post("/sapi/v1/convert/acceptQuote", {"quoteId": q_js["quoteId"]})
    print("[acceptQuote]", a_resp.status_code, a_resp.text)
    try:
        res = a_resp.json()
    except Exception:
        res = {}

    if a_resp.status_code == 200 and res.get("orderId"):
        print("[OK]", {"from": fr, "to": to, "fromAmount": amount_str, "wallet": wallet, "orderId": res.get("orderId")})
        sys.exit(0)
    else:
        print("[!] acceptQuote failed")
        sys.exit(6)

if __name__ == "__main__":
    main()
    print("[exchangeInfo]", ei)

    # --info: показати ліміти і баланси та вийти
    if args.info:
        from_spot = read_free_balance(fr)
        to_spot   = read_free_balance(to)
        try:
            from_fund = read_free_funding(fr)
            to_fund   = read_free_funding(to)
        except Exception:
            from_fund = to_fund = Decimal(0)
        print("[info] FROM:", fr, "min=", ei.get("fromAssetMinAmount"), "max=", ei.get("fromAssetMaxAmount"))
        print("[info] TO  :", to, "min=", ei.get("toAssetMinAmount"),   "max=", ei.get("toAssetMaxAmount"))
        print(f"[balance] {fr} SPOT   =", floor_str_8(from_spot))
        print(f"[balance] {fr} FUNDING=", floor_str_8(from_fund))
        print(f"[balance] {to} SPOT   =", floor_str_8(to_spot))
        print(f"[balance] {to} FUNDING=", floor_str_8(to_fund))
        sys.exit(0)

    # 2) AMOUNT=ALL → беремо free з потрібного гаманця
    if str(args.amount).upper() == "ALL":
        amount_dec = read_free_by_wallet(fr, wallet)
        print(f"[amount=ALL] {fr} free =", floor_str_8(amount_dec))
    else:
        try:
            amount_dec = Decimal(str(args.amount))
        except InvalidOperation:
            print(f"[!] Invalid amount: {args.amount}")
            sys.exit(3)

    # Показати реальний вільний баланс і не йти в acceptQuote, якщо його не вистачає
    free_dec = read_free_by_wallet(fr, wallet)
    print(f"[balance] {fr} free ({wallet}) =", floor_str_8(free_dec))
    if amount_dec > free_dec:
        print(f"[!] Requested {floor_str_8(amount_dec)} {fr} > free {floor_str_8(free_dec)}. Зменшіть суму або поповніть баланс.")
        if not DRY:
            sys.exit(9)
        else:
            print("[dry-run] Продовжуємо тільки для попереднього котирування…")

    # 3) Застосувати min/max і обрізання до 8 знаків (ROUND_DOWN)
    from_min = Decimal(ei.get("fromAssetMinAmount", "0"))
    from_max = Decimal(ei.get("fromAssetMaxAmount", "0"))
    if from_max > 0 and amount_dec > from_max:
        print(f"[!] Amount {floor_str_8(amount_dec)} > max {from_max}")
        sys.exit(4)
    if amount_dec < from_min:
        print(f"[!] Amount {floor_str_8(amount_dec)} < min {from_min}. Спробуйте >={from_min}")
        sys.exit(4)
    amount_str = floor_str_8(amount_dec)

    # 4) getQuote
    q_resp = post("/sapi/v1/convert/getQuote", {
        "fromAsset": fr,
        "toAsset": to,
        "fromAmount": amount_str,
        "walletType": wallet,
    })
    print("[getQuote]", q_resp.status_code, q_resp.text)
    try:
        q_js = q_resp.json()
    except Exception:
        q_js = {}

    if q_resp.status_code != 200 or "quoteId" not in q_js:
        print("[!] No quoteId — перевір баланс/мінімум/пару/гаманець.")
        sys.exit(5)

    if DRY:
        print("[dry-run] skipping acceptQuote")
        sys.exit(0)

    # 5) acceptQuote
    a_resp = post("/sapi/v1/convert/acceptQuote", {"quoteId": q_js["quoteId"]})
    print("[acceptQuote]", a_resp.status_code, a_resp.text)
    try:
        res = a_resp.json()
    except Exception:
        res = {}

    if a_resp.status_code == 200 and res.get("orderId"):
        print("[OK]", {"from": fr, "to": to, "fromAmount": amount_str, "wallet": wallet, "orderId": res.get("orderId")})
        sys.exit(0)
    else:
        print("[!] acceptQuote failed")
        sys.exit(6)

# ---- helpers (визначені ДО запуску main()) ----
def read_free_balance(asset: str) -> Decimal:
    r = get("/api/v3/account", {})
    r.raise_for_status()
    for b in r.json().get("balances", []):
        if b.get("asset") == asset:
            try:
                return Decimal(b.get("free", "0"))
            except InvalidOperation:
                return Decimal(0)
    return Decimal(0)

def read_free_funding(asset: str) -> Decimal:
    # /sapi/v3/asset/getUserAsset повертає масив активів у FUNDING
    r = post("/sapi/v3/asset/getUserAsset", {"needBtcValuation": False})
    r.raise_for_status()
    try:
        for it in r.json():
            if it.get("asset") == asset:
                return Decimal(it.get("free", "0"))
    except Exception:
        return Decimal(0)
    return Decimal(0)

def read_free_by_wallet(asset: str, wallet: str) -> Decimal:
    return read_free_funding(asset) if (wallet or "").upper() == "FUNDING" else read_free_balance(asset)

if __name__ == "__main__":
    main()
