import os
import sys
import pytest

sys.path.insert(0, os.getcwd())

from quote_counter import weight_ticker_24hr
import md_rest


def test_weight_ticker_24hr_single():
    assert weight_ticker_24hr({"symbol": "BTCUSDT"}) == 2


def test_weight_ticker_24hr_multi():
    assert weight_ticker_24hr({"symbols": "[\"BTCUSDT\"]"}) == 40


def test_ticker_24hr_requires_params():
    with pytest.raises(ValueError):
        md_rest.ticker_24hr()
