from decimal import Decimal
import os
import pytest

from src.core.convert_middleware import _norm8

def test_norm8_quantize_down():
    assert _norm8(Decimal("1.123456789")) == Decimal("1.12345678")
    assert _norm8(Decimal("10.000000009")) == Decimal("10.00000000")
    assert _norm8("29.544560675999996") == Decimal("29.54456067")

@pytest.mark.skipif(os.getenv("CI_SKIP_LIVE") == "1", reason="skip live Binance call")
def test_get_quote_accepts_long_fraction():
    from src.core import convert_api
    val = Decimal("10.2203446162121142")
    try:
        convert_api.get_quote("USDT", "BTC", val)
    except Exception as e:
        resp = getattr(e, "response", None)
        code = None
        if resp is not None:
            try:
                code = resp.json().get("code")
            except Exception:
                pass
        raise AssertionError(f"get_quote failed (code={code}) for long fraction {val}") from e
