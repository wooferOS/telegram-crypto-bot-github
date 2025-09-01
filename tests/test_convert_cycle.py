import types
import os
import sys
import types

sys.path.insert(0, os.getcwd())

sys.modules.setdefault('config_dev3', types.SimpleNamespace(TELEGRAM_CHAT_ID='', TELEGRAM_TOKEN=''))
import convert_cycle


def setup_env(monkeypatch):
    monkeypatch.setenv('PAPER', '1')
    monkeypatch.setenv('ENABLE_LIVE', '0')


def test_accept_only_with_orderid(monkeypatch):
    setup_env(monkeypatch)
    quote = {
        'quoteId': 'q1',
        'ratio': 1.0,
        'inverseRatio': 1.0,
        'fromAmount': 1.0,
        'toAmount': 1.0,
        'score': 1.0,
    }
    monkeypatch.setattr(convert_cycle, 'reset_cycle', lambda: None)
    monkeypatch.setattr(convert_cycle, 'should_throttle', lambda *a, **k: False)
    monkeypatch.setattr(convert_cycle, 'filter_top_tokens', lambda tokens, score_threshold, top_n=2: list(tokens.items()))
    monkeypatch.setattr(convert_cycle, 'get_quote', lambda *a, **k: quote)

    records = []

    def fake_log(quote_data, accepted, order_id, error, create_time, dry_run):
        records.append({'accepted': accepted, 'orderId': order_id, 'dryRun': dry_run})

    monkeypatch.setattr(convert_cycle, 'log_conversion_result', fake_log)

    monkeypatch.setattr(convert_cycle, 'accept_quote', lambda qid: {'dryRun': True})
    res = convert_cycle.process_pair('USDT', ['BTC'], 1.0, 0.0)
    assert res is False
    assert records[0]['accepted'] is False
    assert records[0]['dryRun'] is True

    records.clear()
    monkeypatch.setattr(convert_cycle, 'accept_quote', lambda qid: {'orderId': '1', 'createTime': 2})
    res = convert_cycle.process_pair('USDT', ['BTC'], 1.0, 0.0)
    assert res is True
    assert records[0]['accepted'] is True
    assert records[0]['orderId'] == '1'
