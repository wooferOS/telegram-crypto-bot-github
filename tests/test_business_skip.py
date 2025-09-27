def test_business_skip(monkeypatch, caplog):
    from src.core import convert_middleware as mw
    class FakeResp:
        def json(self): return {"code": -2010}
    class Err(Exception):
        def __init__(self): self.response = FakeResp()
    def fake(*a,**k): raise Err()
    monkeypatch.setattr(mw, "_orig_accept_quote", fake)
    with caplog.at_level("WARNING"):
        out = mw._wrapped_accept_quote("q")
        assert out is None
        assert any("business_skip" in r.message for r in caplog.records)
