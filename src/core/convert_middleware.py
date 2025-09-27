import logging

logger = logging.getLogger(__name__)
from random import random
from time import sleep
from .convert_errors import classify
from decimal import Decimal, ROUND_DOWN
from . import convert_api as _real
def _norm8(x):
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return x.quantize(Decimal('0.00000001'), rounding=ROUND_DOWN)

if hasattr(_real, "get_quote"):
    _orig_get_quote = _real.get_quote
    def _wrapped_get_quote(from_asset, to_asset, amount, *args, **kwargs):
        return _orig_get_quote(from_asset, to_asset, _norm8(amount), *args, **kwargs)
    _real.get_quote = _wrapped_get_quote

if hasattr(_real, "accept_quote"):
    _orig_accept_quote = _real.accept_quote


def _wrapped_accept_quote(quote, *args, **kwargs):
    try:
        return _orig_accept_quote(quote, *args, **kwargs)
    except Exception as e:
        from time import sleep
        from random import random
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
        raise

_real.accept_quote = _wrapped_accept_quote
