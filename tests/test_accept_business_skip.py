def test_accept_quote_business_skip(monkeypatch, caplog):
    from src.core import convert_middleware as mw

    class FakeResp:
        def json(self):
            return {"code": -2010}  # бізнес-правило

    class BizError(Exception):
        def __init__(self):
            self.response = FakeResp()

    def fake_accept(quote, *a, **kw):
        raise BizError()

    monkeypatch.setattr(mw, "_orig_accept_quote", fake_accept, raising=True)

    with caplog.at_level("WARNING"):
        out = mw._wrapped_accept_quote("q456")
        assert out is None
        assert any("business_skip" in r.message for r in caplog.records)
