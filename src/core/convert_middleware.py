from __future__ import annotations

import logging
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional

from . import convert_api as _real
from .utils import rand_jitter
from .convert_errors import classify

log = logging.getLogger(__name__)

# Оригінальні функції
_orig_get_quote = _real.get_quote
_orig_accept_quote = _real.accept_quote


# Нормалізація до 8 знаків (вниз)
def _norm8(x: Decimal) -> Decimal:
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return x.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


def _wrapped_get_quote(
    from_asset: str,
    to_asset: str,
    amount: Decimal,
    *args: Any,
    **kwargs: Any,
):
    """
    Обгортка get_quote:
    - нормалізує amount до 8 знаків (ROUND_DOWN) перед викликом.
    """
    return _orig_get_quote(from_asset, to_asset, _norm8(amount), *args, **kwargs)


def _wrapped_accept_quote(quote: Any, *args: Any, **kwargs: Any):
    """
    Обгортка accept_quote:
    - приймає або рядковий quoteId, або об’єкт/словник з полем quoteId/quote_id;
    - при кодах -1021/-429 робить один ретрай із невеликим джитером;
    - при бізнес-кодах (-2010 тощо) — WARN+пропуск (повертає None);
    - інакше — проброс помилки.
    """
    # Узгоджуємо ідентифікатор котирування
    if isinstance(quote, str):
        pass_arg = quote
    else:
        qid: Optional[str] = None
        try:
            qid = getattr(quote, "quote_id", None) or getattr(quote, "quoteId", None)
        except Exception:
            qid = None
        if isinstance(quote, dict):
            qid = qid or quote.get("quoteId") or quote.get("quote_id")
        if not qid:
            raise ValueError("acceptQuote: відсутній quoteId у quote")
        pass_arg = qid

    # Перший виклик
    try:
        return _orig_accept_quote(pass_arg, *args, **kwargs)
    except Exception as e:
        kind = classify(e)
        if kind == "retry":
            # Невелика пауза з джитером і одна спроба повтору
            delay = rand_jitter(0.3, spread=0.2)  # ~0.24..0.36s
            time.sleep(delay)
            return _orig_accept_quote(pass_arg, *args, **kwargs)
        if kind == "business":
            # Бізнес-правило біржі: лог і пропуск
            try:
                code = getattr(getattr(e, "response", None), "json", lambda: {})().get("code")
            except Exception:
                code = None
            log.warning("business_skip: accept_quote skipped by business rule (code=%s, quoteId=%s)", code, pass_arg)
            return None
        # Інше — пробросимо далі
        raise


# Експортуємо назовні обгортки замість оригіналів
get_quote = _wrapped_get_quote
accept_quote = _wrapped_accept_quote
