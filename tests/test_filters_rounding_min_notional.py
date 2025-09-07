import sys
import os
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
        MARKETDATA_BASE_URL="https://data-api.binance.vision",
        SCORING_WEIGHTS={"edge": 1.0, "liquidity": 0.1, "momentum": 0.1, "spread": 0.1, "volatility": 0.1},
    ),
)

sys.path.insert(0, os.getcwd())

import convert_cycle
import exchange_filters
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


def test_filters_rounding_and_min_notional(monkeypatch):
    setup_env(monkeypatch)

    def fake_get(url, params=None, timeout=10):
        class Resp:
            status_code = 200

            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

        return Resp({"price": "2.5"})

    monkeypatch.setattr(exchange_filters, "requests", types.SimpleNamespace(get=fake_get))
    monkeypatch.setattr(
        convert_api,
        "exchange_info",
        lambda **kw: {"toAssetList": [{"toAsset": "USDT", "fromAssetMinAmount": "10"}]},
    )
    monkeypatch.setattr(convert_api, "asset_info", lambda asset: {"asset": asset, "fraction": 2})

    calls = {"get_quote": 0, "amounts": []}

    def fake_get_quote(frm, to, amt, **kwargs):
        calls["get_quote"] += 1
        calls["amounts"].append(amt)
        return {
            "quoteId": "1",
            "ratio": 1.0,
            "inverseRatio": 1.0,
            "fromAmount": amt,
            "toAmount": amt,
            "score": 1.0,
        }

    monkeypatch.setattr(convert_cycle, "get_quote", fake_get_quote)
    monkeypatch.setattr(convert_cycle, "reset_cycle", lambda: None)
    monkeypatch.setattr(convert_cycle, "should_throttle", lambda *a, **k: False)
    monkeypatch.setattr(
        convert_cycle, "filter_top_tokens", lambda tokens, score_threshold, top_n=2: list(tokens.items())
    )

    records = []

    def fake_log(quote, accepted, order_id, error, create_time, order_status, edge, region, step_size, min_notional, px, est_notional, reason):
        records.append(
            {
                "fromAmount": quote.get("fromAmount"),
                "reason": reason,
                "step": step_size,
                "px": px,
                "est": est_notional,
            }
        )

    monkeypatch.setattr(convert_cycle, "log_conversion_result", fake_log)

    convert_cycle.process_pair("AAA", ["BBB"], 3.999, 0.0)
    assert calls["get_quote"] == 0
    assert records and records[0]["reason"] == "skip(minNotional)"
    assert records[0]["fromAmount"] == "3.99"

    records.clear()
    calls["get_quote"] = 0
    convert_cycle.process_pair("AAA", ["BBB"], 4.01, 0.0)
    assert calls["get_quote"] == 1
    assert calls["amounts"][0] == 4.01
