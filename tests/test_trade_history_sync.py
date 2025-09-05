import json
from pathlib import Path

import convert_api
import trade_history_sync


def test_sync_recent_trades(monkeypatch, tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    with open(logs / 'convert_history.json', 'w') as f:
        json.dump([{'quoteId': 'old'}], f)

    calls = []
    monkeypatch.setattr(trade_history_sync, 'log_conversion_result', lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(convert_api, '_current_timestamp', lambda: 1000)

    def fake_trade_flow(startTime, endTime):
        return {
            'list': [
                {'quoteId': 'old'},
                {
                    'quoteId': 'new',
                    'fromAsset': 'A',
                    'toAsset': 'B',
                    'fromAmount': '1',
                    'toAmount': '2',
                    'status': 'SUCCESS',
                    'orderId': '1',
                    'createTime': 5,
                },
            ]
        }

    monkeypatch.setattr(convert_api, 'trade_flow', fake_trade_flow)
    monkeypatch.chdir(tmp_path)
    added = trade_history_sync.sync_recent_trades(minutes=1)
    assert added == 1
    assert calls and calls[0][0][0]['quoteId'] == 'new'
