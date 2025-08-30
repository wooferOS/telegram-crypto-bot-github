import hmac
import hashlib
import os
import sys

sys.path.insert(0, os.getcwd())

import types
import convert_api


def test_sign_deterministic(monkeypatch):
    monkeypatch.setattr(convert_api, 'BINANCE_SECRET_KEY', 'secret')
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 1234567890)
    params = {'fromAsset': 'USDT', 'toAsset': 'BTC'}
    signed = convert_api._sign(params.copy())
    query = 'fromAsset=USDT&toAsset=BTC&recvWindow=20000&timestamp=1234567890'
    expected = hmac.new(b'secret', query.encode(), hashlib.sha256).hexdigest()
    assert signed['signature'] == expected


def test_get_quote_uses_form(monkeypatch):
    sent = {}

    def fake_post(self, url, data=None, params=None, headers=None, timeout=None):
        sent['data'] = data
        sent['params'] = params
        sent['headers'] = headers
        class Resp:
            status_code = 200
            headers = {}
            def json(self):
                return {}
        return Resp()

    monkeypatch.setattr(convert_api, 'increment_quote_usage', lambda: None)
    monkeypatch.setattr(convert_api, '_session', type('S', (), {'post': fake_post})())
    monkeypatch.setattr(convert_api, '_sign', lambda x: x)
    convert_api.get_quote('USDT', 'BTC', 1.0)
    assert sent['params'] is None or sent['params'] == {}
    assert isinstance(sent['data'], dict)
    assert sent['headers']['Content-Type'] == 'application/x-www-form-urlencoded'


def test_time_sync_retry(monkeypatch):
    class Sess:
        def __init__(self):
            self.calls = 0

        def post(self, url, data=None, headers=None, timeout=None, params=None):
            self.calls += 1
            if self.calls == 1:
                class R:
                    status_code = 200
                    headers = {}
                    def json(self):
                        return {"code": -1021}
                return R()
            class R2:
                status_code = 200
                headers = {}
                def json(self):
                    return {"ok": True}
            return R2()

        def get(self, url, params=None, headers=None, timeout=None):
            class R:
                status_code = 200
                headers = {}
                def json(self):
                    return {"serverTime": 1000}
            return R()

    sess = Sess()
    monkeypatch.setattr(convert_api, '_session', sess)
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 0)
    res = convert_api._request('POST', '/sapi/v1/convert/getQuote', {'a': 1})
    assert res == {"ok": True}
    assert sess.calls == 2


def test_backoff_on_429(monkeypatch):
    sleeps: list[float] = []

    class Sess:
        def __init__(self):
            self.calls = 0

        def post(self, url, data=None, headers=None, timeout=None, params=None):
            self.calls += 1
            if self.calls == 1:
                class R:
                    status_code = 429
                    headers = {}
                    def json(self):
                        return {}
                return R()
            class R2:
                status_code = 200
                headers = {}
                def json(self):
                    return {"ok": 1}
            return R2()

    sess = Sess()
    monkeypatch.setattr(convert_api, '_session', sess)
    fake_time = types.SimpleNamespace(sleep=lambda s: sleeps.append(s), time=lambda: 0)
    monkeypatch.setattr(convert_api, 'time', fake_time)
    monkeypatch.setattr(convert_api, 'random', types.SimpleNamespace(uniform=lambda a, b: 0))
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 0)
    res = convert_api._request('POST', '/sapi/v1/convert/getQuote', {'a': 1})
    assert res == {"ok": 1}
    assert sleeps and sleeps[0] > 0


def test_accept_quote_dry_run(monkeypatch):
    called = {}

    def fake_request(*args, **kwargs):
        called['yes'] = True

    monkeypatch.setenv('ENABLE_LIVE', '0')
    monkeypatch.setenv('PAPER', '1')
    monkeypatch.setattr(convert_api, '_request', fake_request)
    res = convert_api.accept_quote('123')
    assert res == {'dryRun': True}
    assert called == {}
