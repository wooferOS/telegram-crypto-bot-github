from __future__ import annotations

ERROR_POLICY = {
    -23000: "fix_amount_and_retry_once",  # «макс. 8 знаків» — ми вже нормалізуємо
    -1021: "sync_time_and_retry",  # Timestamp for this request is outside recvWindow
    -1003: "rate_limit_backoff",  # Too many requests
    -2010: "business_skip",  # new order rejected / business rule
    -2011: "business_skip",  # cancel rejected / business rule
}


def classify(exc) -> str:
    code = None
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            j = resp.json()
            code = j.get("code")
        except Exception:
            pass
    return ERROR_POLICY.get(code, "unknown")
