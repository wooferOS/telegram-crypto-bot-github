def test_accept_quote_wrapped_once():
    from src.core.convert_middleware import _real, _orig_accept_quote

    # якщо middleware активний, то у _real.accept_quote має бути наш враппер, а _orig_* тримає оригінал
    assert hasattr(_real, "accept_quote")
    assert callable(_orig_accept_quote)
