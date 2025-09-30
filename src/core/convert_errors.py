from __future__ import annotations

from typing import Optional

# Коди, які треба ретраїти (часовий дрейф, rate limit)
_RETRY_CODES = {-1021, -429}
# Бізнес-правила біржі: не падати, а логувати й пропускати
_BUSINESS_CODES = {-2010, -2011, -1102, -1111}


def _extract_code(exc: Exception) -> Optional[int]:
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    try:
        data = resp.json()
        code = data.get("code")
        return int(code) if code is not None else None
    except Exception:
        return None


def classify(exc: Exception) -> str:
    """
    Повертає одну з категорій: "retry" | "business" | "other".
    """
    code = _extract_code(exc)
    if code in _RETRY_CODES:
        return "retry"
    if code in _BUSINESS_CODES:
        return "business"
    return "other"
