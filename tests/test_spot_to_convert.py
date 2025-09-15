import sys, os, types
sys.path.insert(0, os.getcwd())
from analysis_utils import spot_to_convert_assets


def test_spot_to_convert_assets():
    symbol = {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"}
    from_asset, to_asset = spot_to_convert_assets(symbol)
    assert from_asset == "BTC" and to_asset == "USDT"
