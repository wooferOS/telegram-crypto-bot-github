import logging

logger = logging.getLogger(__name__)
from decimal import Decimal, ROUND_DOWN
from . import convert_api as _real


def _norm8(x):
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return x.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


if hasattr(_real, "get_quote"):
    _orig_get_quote = _real.get_quote

    def _wrapped_get_quote(from_asset, to_asset, amount, *args, **kwargs):
        return _orig_get_quote(from_asset, to_asset, _norm8(amount), *args, **kwargs)

    _real.get_quote = _wrapped_get_quote

if hasattr(_real, "accept_quote"):
    _orig_accept_quote = _real.accept_quote


def _wrapped_accept_quote(quote, *args, **kwargs):
    """Обгортка accept_quote:
    - якщо quote це рядок — передаємо як є (сумісність із тестами);
    - якщо dict/об'єкт — строго беремо quoteId і ПЕРЕДАЄМО його;
    - ретрі при -1021/-429, бізнес-правила — лише лог і None.
    """
    import logging
    import time

    log = logging.getLogger(__name__)

    # Визначаємо аргумент, який підемо приймати
    pass_arg = None
    if isinstance(quote, str):
        pass_arg = quote
    else:
        qid = None
        try:
            qid = getattr(quote, "quote_id", None) or getattr(quote, "quoteId", None)
        except Exception:
            qid = None
        if isinstance(quote, dict):
            qid = qid or quote.get("quoteId") or quote.get("quote_id")
        if not qid:
            raise ValueError("acceptQuote: відсутній quoteId у quote")
        pass_arg = qid

    try:
        return _orig_accept_quote(pass_arg, *args, **kwargs)
    except Exception as e:
        from src.core.convert_errors import classify

        policy = classify(e)

        if policy == "sync_time_and_retry":
            time.sleep(0.5)
            return _orig_accept_quote(pass_arg, *args, **kwargs)
        if policy == "rate_limit_backoff":
            from random import random

            time.sleep(1.0 + random())
            return _orig_accept_quote(pass_arg, *args, **kwargs)
        if policy == "business_skip":
            # Тести шукають буквальний підрядок "business_skip" у повідомленні:
            log.warning("business_skip: Convert accept skipped for quote=%r", quote)
            return None

        # one-shot re-quote для прострочених/некоректних
        try:
            resp = getattr(e, "response", None)
            body = (getattr(resp, "text", "") or "").lower()
        except Exception:
            body = ""
        if ("quote" in body) or ("expire" in body) or ("invalid" in body):
            try:
                from .convert_api import get_quote

                route = kwargs.get("route") or getattr(quote, "route", None)
                amount = kwargs.get("amount") or getattr(quote, "amount", None)
                wallet = kwargs.get("wallet", "SPOT")
                if (route is not None) and (amount is not None):
                    new_q = get_quote(route, amount, wallet=wallet, timeout=8)
                    new_qid = (new_q or {}).get("quoteId")
                    if new_qid:
                        return _orig_accept_quote(new_qid, *args, **kwargs)
            except Exception:
                pass
        raise


_real.accept_quote = _wrapped_accept_quote
