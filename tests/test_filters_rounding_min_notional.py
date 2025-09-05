import sys
import os
import types

os.environ.setdefault("BINANCE_API_KEY", "k")
os.environ.setdefault("BINANCE_API_SECRET", "s")
sys.modules.setdefault(
    "config_dev3", types.SimpleNamespace(TELEGRAM_CHAT_ID="", TELEGRAM_TOKEN="")
)

sys.path.insert(0, os.getcwd())

import convert_cycle
import exchange_filters


def setup_env(monkeypatch):
    monkeypatch.setenv("PAPER", "1")
    monkeypatch.setenv("ENABLE_LIVE", "0")


def test_filters_rounding_and_min_notional(monkeypatch):
    setup_env(monkeypatch)

    def fake_get(url, params=None, timeout=10):
        class Resp:
            status_code = 200

            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

        if "exchangeInfo" in url:
            data = {
                "symbols": [
                    {
                        "baseAsset": "AAA",
                        "quoteAsset": "USDT",
                        "filters": [
                            {"filterType": "LOT_SIZE", "stepSize": "0.01"},
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
                        ],
                    }
                ]
            }
            return Resp(data)
        data = {"price": "2.5"}
        return Resp(data)

    monkeypatch.setattr(exchange_filters, "requests", types.SimpleNamespace(get=fake_get))

    calls = {"get_quote": 0, "amounts": []}

    def fake_get_quote(frm, to, amt):
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

    def fake_log(quote, accepted, order_id, error, create_time, dry_run, order_status, mode, edge, region, step_size, min_notional, px, est_notional, reason):
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
