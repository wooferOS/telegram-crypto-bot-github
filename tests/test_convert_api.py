import hmac
import hashlib
import os
import sys
import pytest

sys.path.insert(0, os.getcwd())

import types
import convert_api


def test_sign_deterministic(monkeypatch):
    monkeypatch.setattr(convert_api, 'BINANCE_SECRET_KEY', 'secret')
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 1234567890)
    params = {'fromAsset': 'USDT', 'toAsset': 'BTC'}
    signed = convert_api._sign(params.copy())
    query = 'fromAsset=USDT&toAsset=BTC&recvWindow=5000&timestamp=1234567890'
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


def test_request_adds_signature_and_header(monkeypatch):
    sent = {}

    def fake_post(self, url, data=None, params=None, headers=None, timeout=None):
        sent['data'] = data
        sent['headers'] = headers
        class Resp:
            status_code = 200
            headers = {}
            def json(self):
                return {}
        return Resp()

    monkeypatch.setattr(convert_api, '_session', type('S', (), {'post': fake_post})())
    monkeypatch.setattr(convert_api, 'BINANCE_SECRET_KEY', 'secret')
    monkeypatch.setattr(convert_api, 'BINANCE_API_KEY', 'key')
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 1)

    convert_api._request('POST', '/sapi/v1/convert/getQuote', {'a': 1})
    assert 'timestamp' in sent['data'] and 'signature' in sent['data']
    assert sent['headers']['X-MBX-APIKEY'] == 'key'


def test_clock_skew_sync(monkeypatch):
    class Sess:
        def __init__(self):
            self.calls = 0

        def post(self, url, data=None, headers=None, timeout=None, params=None):
            self.calls += 1
            class R:
                status_code = 200
                headers = {}
                def json(inner_self):
                    if self.calls == 1:
                        return {"code": -1021}
                    return {"ok": 1}
            return R()

        def get(self, url, params=None, headers=None, timeout=None):
            class R:
                status_code = 200
                headers = {}
                def json(self):
                    return {"serverTime": 5}
            return R()

    sess = Sess()
    monkeypatch.setattr(convert_api, '_session', sess)
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 0)
    convert_api._time_offset_ms = 0
    res = convert_api._request('POST', '/sapi/v1/convert/getQuote', {'a': 1})
    assert res == {"ok": 1}
    assert convert_api._time_offset_ms == 5
    convert_api._time_offset_ms = 0


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


def test_invalid_signature(monkeypatch):
    class Sess:
        def post(self, url, data=None, headers=None, timeout=None, params=None):
            class R:
                status_code = 200
                headers = {}
                def json(self):
                    return {"code": -1022}
            return R()

    monkeypatch.setattr(convert_api, '_session', Sess())
    with pytest.raises(ValueError):
        convert_api._request('POST', '/sapi/v1/convert/getQuote', {'a': 1})


def test_missing_param(monkeypatch):
    class Sess:
        def post(self, url, data=None, headers=None, timeout=None, params=None):
            class R:
                status_code = 200
                headers = {}
                def json(self):
                    return {"code": -1102}
            return R()

    monkeypatch.setattr(convert_api, '_session', Sess())
    with pytest.raises(ValueError):
        convert_api._request('POST', '/sapi/v1/convert/getQuote', {'a': 1})


def test_rate_limit_error(monkeypatch):
    sleeps: list[float] = []

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
                        return {"code": -1003}
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


def test_exchange_info_cache(monkeypatch):
    calls = []

    def fake_request(method, path, params, *, signed=False):
        calls.append(t.val)
        return {"value": len(calls)}

    # monkeypatch time.time so we can simulate TTL expiry
    t = types.SimpleNamespace(val=0.0)
    def time_fn():
        return t.val
    monkeypatch.setattr(convert_api, 'time', types.SimpleNamespace(time=time_fn))

    monkeypatch.setattr(convert_api, '_request', fake_request)
    monkeypatch.setattr(convert_api, '_exchange_info_cache', None)

    convert_api.exchange_info()          # call at t=0 -> request
    convert_api.exchange_info()          # still t=0 -> cached
    t.val = convert_api.PAIRS_TTL + 1
    convert_api.exchange_info()          # after TTL -> new request
    assert len(calls) == 2



def test_accept_quote_dry_run(monkeypatch):
    called = {}

    def fake_request(*args, **kwargs):
        called['yes'] = True

    monkeypatch.setenv('ENABLE_LIVE', '0')
    monkeypatch.setenv('PAPER', '1')
    monkeypatch.setattr(convert_api, '_request', fake_request)
    res = convert_api.accept_quote('123')
    assert res.get('dryRun') is True
    assert 'orderId' not in res
    assert called == {}


def test_get_quote_with_id_params(monkeypatch):
    sent = {}

    def fake_request(method, path, params):
        sent['method'] = method
        sent['path'] = path
        sent['params'] = params
        return {}

    monkeypatch.setattr(convert_api, '_request', fake_request)
    monkeypatch.setattr(convert_api, 'increment_quote_usage', lambda: None)
    convert_api.get_quote_with_id('USDT', 'BTC', from_amount=1.23, walletType='MAIN')
    assert sent['method'] == 'POST'
    assert sent['path'] == '/sapi/v1/convert/getQuote'
    assert sent['params']['fromAsset'] == 'USDT'
    assert sent['params']['toAsset'] == 'BTC'
    assert sent['params']['fromAmount'] == 1.23
    assert sent['params']['walletType'] == 'MAIN'
    assert sent['params']['recvWindow'] == convert_api.DEFAULT_RECV_WINDOW


def test_get_quote_signed(monkeypatch):
    sent = {}

    def fake_post(self, url, data=None, params=None, headers=None, timeout=None):
        sent['data'] = data
        sent['headers'] = headers
        class R:
            status_code = 200
            headers = {}
            def json(self):
                return {}
        return R()

    monkeypatch.setattr(convert_api, '_session', type('S', (), {'post': fake_post})())
    monkeypatch.setattr(convert_api, 'BINANCE_SECRET_KEY', 'secret')
    monkeypatch.setattr(convert_api, 'BINANCE_API_KEY', 'key')
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 1)
    monkeypatch.setattr(convert_api, 'increment_quote_usage', lambda: None)
    convert_api._time_offset_ms = 0
    convert_api.get_quote_with_id('USDT', 'BTC', from_amount=1.0)
    assert 'fromAmount' in sent['data'] and 'toAmount' not in sent['data']
    assert sent['data']['timestamp'] == 1
    assert sent['data']['recvWindow'] == convert_api.DEFAULT_RECV_WINDOW
    assert sent['headers']['X-MBX-APIKEY'] == 'key'


def test_get_quote_with_id_validation(monkeypatch):
    monkeypatch.setattr(convert_api, 'increment_quote_usage', lambda: None)
    with pytest.raises(ValueError):
        convert_api.get_quote_with_id('USDT', 'BTC', from_amount=1, to_amount=2)
    with pytest.raises(ValueError):
        convert_api.get_quote_with_id('USDT', 'BTC')


def test_accept_quote_live(monkeypatch):
    sent = {}

    def fake_post(self, url, data=None, headers=None, timeout=None, params=None):
        sent['data'] = data
        sent['headers'] = headers
        class R:
            status_code = 200
            headers = {}
            def json(self):
                return {'orderId': '1', 'createTime': 2}
        return R()

    monkeypatch.setenv('PAPER', '0')
    monkeypatch.setenv('ENABLE_LIVE', '1')
    monkeypatch.setattr(convert_api, '_session', type('S', (), {'post': fake_post})())
    monkeypatch.setattr(convert_api, 'BINANCE_SECRET_KEY', 'secret')
    monkeypatch.setattr(convert_api, 'BINANCE_API_KEY', 'key')
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 1)
    convert_api._time_offset_ms = 0
    res = convert_api.accept_quote('abc', walletType='MAIN')
    assert res == {'orderId': '1', 'createTime': 2}
    assert sent['data']['quoteId'] == 'abc'
    assert sent['data']['timestamp'] == 1
    assert 'signature' in sent['data']
    assert sent['headers']['X-MBX-APIKEY'] == 'key'


def test_get_order_status_params(monkeypatch):
    sent = {}

    def fake_request(method, path, params):
        sent['method'] = method
        sent['path'] = path
        sent['params'] = params
        return {
            'orderStatus': 'SUCCESS',
            'fromAsset': 'USDT',
            'fromAmount': '1',
            'toAsset': 'BTC',
            'toAmount': '0.1',
            'ratio': '0.1',
        }

    monkeypatch.setattr(convert_api, '_request', fake_request)
    res = convert_api.get_order_status(orderId='1')
    assert res['orderStatus'] == 'SUCCESS'


def test_accept_quote_idempotent(monkeypatch):
    monkeypatch.setenv('PAPER', '0')
    monkeypatch.setenv('ENABLE_LIVE', '1')

    class Sess:
        def post(self, url, data=None, headers=None, timeout=None, params=None):
            class R:
                status_code = 200
                headers = {}
                def json(self):
                    return {}
            return R()

    monkeypatch.setattr(convert_api, '_session', Sess())
    monkeypatch.setattr(convert_api, 'BINANCE_SECRET_KEY', 'secret')
    monkeypatch.setattr(convert_api, 'BINANCE_API_KEY', 'key')
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 1)
    convert_api._time_offset_ms = 0
    convert_api._accepted_quotes.clear()
    convert_api.accept_quote('dup')
    res = convert_api.accept_quote('dup')
    assert res.get('duplicate') is True


def test_trade_flow_params(monkeypatch):
    sent = {}

    def fake_request(method, path, params):
        sent['method'] = method
        sent['path'] = path
        sent['params'] = params
        return {'list': [1], 'cursor': 'next'}

    monkeypatch.setattr(convert_api, '_request', fake_request)
    res = convert_api.trade_flow(startTime=1, endTime=2, limit=3, cursor='abc')
    assert sent['path'] == '/sapi/v1/convert/tradeFlow'
    assert sent['params'] == {'startTime': 1, 'endTime': 2, 'limit': 3, 'cursor': 'abc'}
    assert res == {'list': [1], 'cursor': 'next'}


def test_trade_flow_pagination(monkeypatch):
    calls = []

    def fake_request(method, path, params):
        calls.append(params.get('cursor'))
        return {'list': [], 'cursor': 'next' if params.get('cursor') is None else None}

    monkeypatch.setattr(convert_api, '_request', fake_request)
    first = convert_api.trade_flow(startTime=0, endTime=1)
    assert first['cursor'] == 'next'
    second = convert_api.trade_flow(startTime=0, endTime=1, cursor=first['cursor'])
    assert second['cursor'] is None
    assert calls == [None, 'next']


def test_exchange_info_public(monkeypatch):
    sent = {}

    class Sess:
        def get(self, url, params=None, headers=None, timeout=None):
            sent['params'] = params
            sent['headers'] = headers
            class R:
                status_code = 200
                headers = {}
                def json(self):
                    return {}
            return R()

    monkeypatch.setattr(convert_api, '_session', Sess())
    monkeypatch.setattr(convert_api, '_exchange_info_cache', None)
    convert_api.exchange_info()
    assert sent['headers'] is None
    assert 'signature' not in (sent['params'] or {})


def test_get_quote_live_no_paper(monkeypatch):
    called = {}

    def fake_request(method, path, params):
        called['path'] = path
        return {'ok': True}

    monkeypatch.setenv('PAPER', '0')
    monkeypatch.setattr(convert_api, '_request', fake_request)
    monkeypatch.setattr(convert_api, 'increment_quote_usage', lambda: None)
    res = convert_api.get_quote('USDT', 'BTC', 1.0)
    assert res == {'ok': True}
    assert called['path'] == '/sapi/v1/convert/getQuote'


def test_permission_error(monkeypatch):
    class Sess:
        def post(self, url, data=None, headers=None, timeout=None, params=None):
            class R:
                status_code = 200
                headers = {}
                def json(self):
                    return {'code': -2015}
            return R()

    monkeypatch.setattr(convert_api, '_session', Sess())
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 0)
    monkeypatch.setattr(convert_api, 'BINANCE_SECRET_KEY', 'secret')
    monkeypatch.setattr(convert_api, 'BINANCE_API_KEY', 'key')

    with pytest.raises(PermissionError):
        convert_api._request('POST', '/sapi/v1/convert/getQuote', {'a': 1})
