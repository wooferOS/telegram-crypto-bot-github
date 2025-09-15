import os, sys, types
sys.path.insert(0, os.getcwd())

sys.modules.setdefault(
    "config_dev3",
    types.SimpleNamespace(
        SCORING_WEIGHTS={
            "edge": 1.0,
            "liquidity": 0.1,
            "momentum": 0.1,
            "spread": 0.1,
            "volatility": 0.1,
        }
    ),
)

import scoring
import md_rest
import mid_ref
import config_dev3


def test_score_pair(monkeypatch):
    def fake_mid(from_asset, to_asset, *, with_symbol=False):
        if with_symbol:
            return 10.0, "FT"
        return 10.0

    monkeypatch.setattr(mid_ref, "get_mid_price", fake_mid)
    monkeypatch.setattr(md_rest, "book_ticker", lambda s: {"bidPrice": "9", "askPrice": "11"})
    monkeypatch.setattr(md_rest, "ticker_24hr", lambda s: {"quoteVolume": "1000", "count": "100"})
    monkeypatch.setattr(
        md_rest,
        "klines",
        lambda s, interval, limit: [[0, "9", "12", "8", "10"], [0, "10", "12", "8", "11"]],
    )
    monkeypatch.setattr(
        config_dev3,
        "SCORING_WEIGHTS",
        {"edge": 1.0, "liquidity": 0.1, "momentum": 0.1, "spread": 0.1, "volatility": 0.1},
        raising=False,
    )

    res = scoring.score_pair("F", "T", 10.5)
    assert res is not None
    assert abs(res["edge"] - 0.05) < 1e-9
    expected = 0.05 + 0.0011 + 0.0222222222 - 0.02 - 0.04
    assert abs(res["score"] - expected) < 1e-6
