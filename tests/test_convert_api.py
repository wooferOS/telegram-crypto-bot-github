import hmac
import hashlib

import os
import sys

sys.path.insert(0, os.getcwd())

import convert_api


def test_sign_deterministic(monkeypatch):
    monkeypatch.setattr(convert_api, 'BINANCE_SECRET_KEY', 'secret')
    monkeypatch.setattr(convert_api, 'get_current_timestamp', lambda: 1234567890)
    params = {'fromAsset': 'USDT', 'toAsset': 'BTC'}
    signed = convert_api._sign(params.copy())
    query = 'fromAsset=USDT&toAsset=BTC&timestamp=1234567890'
    expected = hmac.new(b'secret', query.encode(), hashlib.sha256).hexdigest()
    assert signed['signature'] == expected


def test_get_quote_uses_form(monkeypatch):
    sent = {}

    def fake_post(self, url, data=None, params=None, headers=None, timeout=None):
        sent['data'] = data
        sent['params'] = params
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
