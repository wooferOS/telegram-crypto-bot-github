import sys, os
sys.path.insert(0, os.getcwd())
from analysis_utils import detect_new_listings


def test_detect_new_listings():
    prev = {"symbols": [{"symbol": "AAAUSDT"}, {"symbol": "BBBUSDT"}]}
    curr = {"symbols": [
        {"symbol": "AAAUSDT", "status": "TRADING"},
        {"symbol": "BBBUSDT", "status": "TRADING"},
        {"symbol": "DDDUSDT", "status": "TRADING"},
        {"symbol": "EEEUSDT", "status": "BREAK"},
    ]}
    assert detect_new_listings(prev, curr) == ["DDDUSDT"]
