from config_dev3 import BINANCE_API_KEY, BINANCE_SECRET_KEY
import os, json, time, hashlib, threading
from datetime import datetime, timezone
from pathlib import Path
import requests

# --- Конфіг за замовчуванням (можна перевизначати через env) ---
HOURLY_BUDGET = int(os.environ.get("CONVERT_QUOTE_HOURLY_BUDGET", "60"))
PER_MIN_RATE  = int(os.environ.get("CONVERT_QUOTE_PER_MIN_RATE", "6"))
CACHE_TTL_SEC = int(os.environ.get("CONVERT_QUOTE_CACHE_TTL", "45"))
STATE_FILE    = Path(os.environ.get("CONVERT_QUOTE_STATE_FILE", "/srv/dev3/quote_guard/state.json"))
BLOCK_ANALYSIS= os.environ.get("DISABLE_CONVERT_FOR_ANALYSIS", "1") == "1"
ANALYSIS_HINT = "daily_analysis.py"

_lock = threading.RLock()
_state = {
    "hour": None,
    "used": 0,
    "mute_until": 0,
    "per_minute": {"minute": None, "used": 0},
    "cache": {}
}

def _load_state():
    """Завантажуємо стан із файлу"""
    global _state
    try:
        if STATE_FILE.exists() and STATE_FILE.stat().st_size > 0:
            _state = json.loads(STATE_FILE.read_text())
    except Exception:
        pass

def _save_state():
    """Зберігаємо стан у файл"""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_state, ensure_ascii=False))
        tmp.replace(STATE_FILE)
    except Exception:
        pass

def _now():
    return int(time.time())

def _current_hour_key(ts=None):
    ts = ts or _now()
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d-%H")

def _current_minute_key(ts=None):
    ts = ts or _now()
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d-%H-%M")



def _check_rate_limits(sig: str):
    """Перевіряє ліміти на запити та кеш"""
    ts = _now()
    hour_key = _current_hour_key(ts)
    minute_key = _current_minute_key(ts)

    with _lock:
        _load_state()

        # --- Кеш ---
        if sig in _state["cache"]:
            cached_ts = _state["cache"][sig]
            if ts - cached_ts < CACHE_TTL_SEC:
                return False, "cache-hit"

        # --- Хвилинний ліміт ---
        if _state["per_minute"]["minute"] != minute_key:
            _state["per_minute"] = {"minute": minute_key, "used": 0}
        if _state["per_minute"]["used"] >= PER_MIN_RATE:
            return False, "per-minute-limit"

        # --- Годинний ліміт ---
        if _state["hour"] != hour_key:
            _state["hour"], _state["used"] = hour_key, 0
        if _state["used"] >= HOURLY_BUDGET:
            return False, "hourly-limit"

        # --- Запис ---
        _state["per_minute"]["used"] += 1
        _state["used"] += 1
        _state["cache"][sig] = ts
        _save_state()

    return True, "ok"
    return True, "ok"

def _binance_345103_response():
    """Формує синтетичну відповідь Binance 345103"""
    r = requests.Response()
    r.status_code = 400
    r._content = b'{"code":345103,"msg":"Your hourly quotation limit is reached. Please try again later in the next hour."}'
    r.headers["Content-Type"] = "application/json"
    r.reason = "Bad Request"
    r.url = ""
    return r

# --- Перехоплення requests ---
_real_request = requests.Session.request

def _guarded_request(self, method, url, *a, **kw):
    try:
        # якщо не convert — пропускаємо
        print("[GUARD] DISABLE_CONVERT_FOR_ANALYSIS flag detected")
        if os.environ.get("DISABLE_CONVERT_FOR_ANALYSIS","0") == "1":
            print("[GUARD] Blocked convert call by DISABLE_CONVERT_FOR_ANALYSIS")
            print("[GUARD] Triggered fake 345103 response")
            return _binance_345103_response()
        if "/sapi/" not in url or "/convert/" not in url:
            return _real_request(self, method, url, *a, **kw)

        # --- сигнатура запиту для кешу ---
        sig = method.upper() + "|" + url
        if "json" in kw and kw["json"] is not None:
            sig += "|" + json.dumps(kw["json"], sort_keys=True)
        elif "data" in kw and kw["data"] is not None:
            try: sig += "|" + json.dumps(kw["data"], sort_keys=True)
            except Exception: sig += "|" + str(kw["data"])

        # --- перевіряємо ліміти ---
        ok, reason = _check_rate_limits(sig)
        if not ok:
            print("[GUARD] Blocked convert call by DISABLE_CONVERT_FOR_ANALYSIS")
            print("[GUARD] Triggered fake 345103 response")
            return _binance_345103_response()

        # --- виконуємо реальний запит ---
        r = _real_request(self, method, url, *a, **kw)

        # якщо Binance повернув 345103 — м’ют до кінця години
        try:
            if r.headers.get("Content-Type", "").startswith("application/json"):
                d = r.json()
                if isinstance(d, dict) and str(d.get("code")) == "345103":
                    with _lock:
                        _load_state()
                        _state["mute_until"] = _now() + 3600
                        _save_state()
        except Exception:
            pass

        return r
    except Exception:
        return _real_request(self, method, url, *a, **kw)

requests.Session.request = _guarded_request
