def test_accept_quote_retry(monkeypatch):
    from src.core import convert_middleware as mw
    calls = {"n": 0}

    class FakeResp:
        def json(self): return {"code": -1021}
    class Err(Exception):
        def __init__(self): self.response = FakeResp()

    def fake(quote,*a,**k):
        calls["n"] += 1
        if calls["n"] == 1: raise Err()
        return {"ok":1}

    monkeypatch.setattr(mw, "_orig_accept_quote", fake)
    out = mw._wrapped_accept_quote("q")
    assert out == {"ok":1}
    assert calls["n"] == 2
