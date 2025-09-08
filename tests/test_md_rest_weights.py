import os
import sys
import types
import json
import pytest


sys.modules.setdefault(
    "config_dev3",
    types.SimpleNamespace(
        BINANCE_API_KEY="k",
        BINANCE_API_SECRET="s",
        OPENAI_API_KEY="",
        TELEGRAM_TOKEN="",
        CHAT_ID="",
        DEV3_REGION_TIMER="ASIA",
        DEV3_RECV_WINDOW_MS=5000,
        DEV3_RECV_WINDOW_MAX_MS=60000,
        API_BASE="https://api.binance.com",
        MARKETDATA_BASE="https://data-api.binance.vision",
        SCORING_WEIGHTS={
            "edge": 1.0,
            "liquidity": 0.1,
            "momentum": 0.1,
            "spread": 0.1,
            "volatility": 0.1,
        },
    ),
)

sys.path.insert(0, os.getcwd())

from quote_counter import (
    weight_ticker_24hr,
    weight_ticker_price,
    weight_book_ticker,
)
import md_rest


def test_weight_ticker_24hr():
    assert weight_ticker_24hr({"symbol": "BTCUSDT"}) == 2
    symbols = json.dumps([f"ASSET{i}" for i in range(30)])
    assert weight_ticker_24hr({"symbols": symbols}) == 40
    with pytest.raises(ValueError):
        md_rest.ticker_24hr()


def test_weight_ticker_price_and_guard():
    assert weight_ticker_price({"symbol": "BTCUSDT"}) == 2
    assert weight_ticker_price({}) == 4
    with pytest.raises(ValueError):
        md_rest.ticker_price()


def test_weight_book_ticker_and_guard():
    assert weight_book_ticker({"symbol": "BTCUSDT"}) == 2
    assert weight_book_ticker({}) == 4
    with pytest.raises(ValueError):
        md_rest.book_ticker()

