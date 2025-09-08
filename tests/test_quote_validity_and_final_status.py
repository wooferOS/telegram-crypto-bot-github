import os
import sys
import types

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
        SCORING_WEIGHTS={"edge": 1.0, "liquidity": 0.1, "momentum": 0.1, "spread": 0.1, "volatility": 0.1},
    ),
)

sys.path.insert(0, os.getcwd())

import convert_cycle
import convert_api


def setup_env(monkeypatch):
    monkeypatch.setattr(convert_cycle, "check_risk", lambda: (0, 0))
    monkeypatch.setattr(
        convert_cycle,
        "scoring",
        types.SimpleNamespace(score_pair=lambda f, t, r: {"edge": 0.0, "score": r}),
    )
    monkeypatch.setattr(convert_cycle, "log_cycle_summary", lambda: None)
    monkeypatch.setattr(convert_cycle, "set_cycle_limit", lambda limit: None)


def test_expired_quote_skipped(monkeypatch):
    setup_env(monkeypatch)
    monkeypatch.setattr(convert_cycle, "reset_cycle", lambda: None)
    monkeypatch.setattr(convert_cycle, "should_throttle", lambda *a, **k: False)
    monkeypatch.setattr(convert_cycle, "load_symbol_filters", lambda *a, **k: (None, None, None))
    monkeypatch.setattr(convert_cycle, "get_last_price_usdt", lambda *a, **k: None)
    monkeypatch.setattr(
        convert_cycle, "filter_top_tokens", lambda tokens, score_threshold, top_n=2: list(tokens.items())
    )
    current = 1000
    monkeypatch.setattr(convert_api, "_current_timestamp", lambda: current)
    quote = {
        "quoteId": "q1",
        "ratio": 1.0,
        "inverseRatio": 1.0,
        "fromAmount": 1.0,
        "toAmount": 1.0,
        "score": 1.0,
        "validTimestamp": current - 1,
    }
    monkeypatch.setattr(convert_cycle, "get_quote", lambda *a, **k: quote)
    calls = {"accept": 0}
    monkeypatch.setattr(convert_cycle, "accept_quote", lambda qid: calls.__setitem__("accept", calls["accept"] + 1))
    monkeypatch.setattr(convert_cycle, "log_conversion_result", lambda *a, **k: None)
    res = convert_cycle.process_pair("USDT", ["BTC"], 1.0, 0.0)
    assert res is False
    assert calls["accept"] == 0


def test_only_success_recorded(monkeypatch):
    setup_env(monkeypatch)
    monkeypatch.setattr(convert_cycle, "reset_cycle", lambda: None)
    monkeypatch.setattr(convert_cycle, "should_throttle", lambda *a, **k: False)
    monkeypatch.setattr(convert_cycle, "load_symbol_filters", lambda *a, **k: (None, None, None))
    monkeypatch.setattr(convert_cycle, "get_last_price_usdt", lambda *a, **k: None)
    monkeypatch.setattr(
        convert_cycle, "filter_top_tokens", lambda tokens, score_threshold, top_n=2: list(tokens.items())
    )
    monkeypatch.setattr(convert_api, "_current_timestamp", lambda: 1000)
    quote = {
        "quoteId": "q2",
        "ratio": 1.0,
        "inverseRatio": 1.0,
        "fromAmount": 1.0,
        "toAmount": 1.0,
        "score": 1.0,
        "validTimestamp": 2000,
    }
    monkeypatch.setattr(convert_cycle, "get_quote", lambda *a, **k: quote)
    monkeypatch.setattr(convert_cycle, "log_conversion_result", lambda *a, **k: None)
    monkeypatch.setattr(convert_cycle, "accept_quote", lambda qid: {"orderId": "1", "createTime": 2})
    monkeypatch.setattr(convert_cycle, "get_order_status", lambda **k: {"orderStatus": "FAIL"})
    res = convert_cycle.process_pair("USDT", ["BTC"], 1.0, 0.0)
    assert res is False

    monkeypatch.setattr(convert_cycle, "get_order_status", lambda **k: {"orderStatus": "SUCCESS"})
    res = convert_cycle.process_pair("USDT", ["BTC"], 1.0, 0.0)
    assert res is True
