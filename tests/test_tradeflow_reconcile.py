import json
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

import convert_api
import trade_history_sync


def test_tradeflow_reconcile(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    with open(logs / "convert_history.json", "w") as f:
        json.dump([{ "quoteId": "old" }], f)

    monkeypatch.setattr(convert_api, "_current_timestamp", lambda: 1000)

    def fake_trade_flow(startTime, endTime):
        return {
            "list": [
                {"quoteId": "old"},
                {
                    "quoteId": "new",
                    "fromAsset": "A",
                    "toAsset": "B",
                    "fromAmount": "1",
                    "toAmount": "2",
                    "status": "SUCCESS",
                    "orderId": "1",
                    "createTime": 5,
                },
            ]
        }

    monkeypatch.setattr(convert_api, "trade_flow", fake_trade_flow)

    records = []
    monkeypatch.setattr(trade_history_sync, "log_conversion_result", lambda *a, **k: records.append(a[0]))
    monkeypatch.chdir(tmp_path)

    added = trade_history_sync.sync_recent_trades(minutes=1)
    assert added == 1
    assert records and records[0]["quoteId"] == "new"
