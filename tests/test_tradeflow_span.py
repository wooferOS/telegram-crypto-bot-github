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


def test_tradeflow_span_limit():
    span = 31 * 24 * 60 * 60 * 1000 + 1
    with pytest.raises(ValueError):
        convert_api.trade_flow(0, span)
