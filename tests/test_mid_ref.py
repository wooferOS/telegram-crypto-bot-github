import os, sys
sys.path.insert(0, os.getcwd())

import mid_ref


def test_direct_symbol(monkeypatch):
    mapping = {"ETHUSDT": 1000.0}
    monkeypatch.setattr(mid_ref, "_spot_mid", lambda s: mapping.get(s))
    assert mid_ref.get_mid_price("ETH", "USDT") == 1000.0


def test_cross_via_usdt(monkeypatch):
    mapping = {"BTCUSDT": 20000.0, "ETHUSDT": 1000.0}
    monkeypatch.setattr(mid_ref, "_spot_mid", lambda s: mapping.get(s))
    assert mid_ref.get_mid_price("BTC", "ETH") == 20.0
