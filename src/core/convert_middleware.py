import logging

logger = logging.getLogger(__name__)
from time import sleep
from random import random
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
    # DEV3: strict check for quoteId
    qid = (
        quote
        if isinstance(quote, str)
        else (((quote or {}).get("quoteId")) if isinstance(quote, dict) else getattr(quote, "quoteId", None))
    )
    assert qid, "acceptQuote(): missing quoteId"
    try:
        return _orig_accept_quote(quote, *args, **kwargs)
    except Exception as e:
        from src.core.convert_errors import classify

        policy = classify(e)
        if policy == "sync_time_and_retry":
            sleep(0.5)
            return _orig_accept_quote(quote, *args, **kwargs)
        if policy == "rate_limit_backoff":
            sleep(1.0 + random())
            return _orig_accept_quote(quote, *args, **kwargs)
        if policy == "business_skip":
            logger.warning("Convert business_skip for quote=%s", quote)
            return None
        # DEV3: one-shot re-quote for expired/invalid quote
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
                    assert new_q.get("quoteId")
                    return _orig_accept_quote(new_q, *args, **kwargs)
            except Exception:
                pass
        raise


_real.accept_quote = _wrapped_accept_quote
