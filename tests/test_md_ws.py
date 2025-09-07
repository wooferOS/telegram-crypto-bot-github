import os, sys
sys.path.insert(0, os.getcwd())

from md_ws import build_combined_stream


def test_build_combined_stream_url():
    url = build_combined_stream(["btcusdt@bookTicker", "ethusdt@avgPrice"])
    assert (
        url
        == "wss://data-stream.binance.vision/stream?streams=btcusdt@bookTicker/ethusdt@avgPrice"
    )
