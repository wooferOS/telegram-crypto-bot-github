import sys, os
sys.path.insert(0, os.getcwd())
from analysis_utils import rank_symbols


def test_rank_symbols():
    stats = [
        {"symbol": "AAAUSDT", "priceChangePercent": "5", "quoteVolume": "100000"},
        {"symbol": "BBBUSDT", "priceChangePercent": "2", "quoteVolume": "500000"},
        {"symbol": "CCCUSDT", "priceChangePercent": "1", "quoteVolume": "1000"},
    ]
    klines = {
        "AAAUSDT": [[0,0,0,0,10],[0,0,0,0,11]],  # momentum +10%
        "BBBUSDT": [[0,0,0,0,10],[0,0,0,0,10.5]],  # momentum +5%
        "CCCUSDT": [[0,0,0,0,10],[0,0,0,0,9]],    # momentum -10%
    }
    ranked = rank_symbols(stats, klines, min_quote_volume=10000)
    assert ranked == ["AAAUSDT", "BBBUSDT"]
