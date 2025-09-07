import os
import sys
import types
import pytest

sys.modules['config_dev3'] = types.SimpleNamespace(
    BINANCE_API_KEY='k',
    BINANCE_API_SECRET='s',
    OPENAI_API_KEY='',
    TELEGRAM_TOKEN='',
    CHAT_ID='',
    DEV3_REGION_TIMER='ASIA',
    DEV3_RECV_WINDOW_MS=5000,
    DEV3_RECV_WINDOW_MAX_MS=60000,
    MARKETDATA_BASE_URL='https://data-api.binance.vision',
    SCORING_WEIGHTS={'edge': 1.0, 'liquidity': 0.1, 'momentum': 0.1, 'spread': 0.1, 'volatility': 0.1},
)

sys.path.insert(0, os.getcwd())
import importlib
import convert_api
importlib.reload(convert_api)


def test_recv_window_clamped(monkeypatch):
    monkeypatch.setattr(convert_api, '_current_timestamp', lambda: 0)
    params = convert_api._build_signed_params({'recvWindow': 120000})
    assert params['recvWindow'] == 60000


def test_recv_window_default(monkeypatch):
    monkeypatch.setattr(convert_api, '_current_timestamp', lambda: 0)
    params = convert_api._build_signed_params({})
    assert params['recvWindow'] == 5000
