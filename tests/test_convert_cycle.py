import types
import os
import sys
import types

sys.path.insert(0, os.getcwd())

sys.modules.setdefault('config_dev3', types.SimpleNamespace(TELEGRAM_CHAT_ID='', TELEGRAM_TOKEN=''))
import convert_cycle
import convert_api


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

    def fake_log(quote_data, accepted, order_id, error, create_time, dry_run, order_status=None, mode=None, edge=None, region=None):
        records.append({'accepted': accepted, 'orderId': order_id, 'dryRun': dry_run})

    monkeypatch.setattr(convert_cycle, 'log_conversion_result', fake_log)

    calls = {'accept': 0}

    def fake_accept(qid):
        calls['accept'] += 1
        return {'dryRun': True}

    monkeypatch.setattr(convert_cycle, 'accept_quote', fake_accept)
    res = convert_cycle.process_pair('USDT', ['BTC'], 1.0, 0.0)
    assert res is False
    assert records[0]['accepted'] is False
    assert records[0]['dryRun'] is True
    assert calls['accept'] == 0

    # live mode
    records.clear()
    calls['accept'] = 0
    monkeypatch.setenv('PAPER', '0')
    monkeypatch.setenv('ENABLE_LIVE', '1')

    def fake_accept_live(qid):
        calls['accept'] += 1
        return {'orderId': '1', 'createTime': 2}

    monkeypatch.setattr(convert_cycle, 'accept_quote', fake_accept_live)
    monkeypatch.setattr(convert_cycle, 'get_order_status', lambda **k: {'orderStatus': 'SUCCESS'})
    res = convert_cycle.process_pair('USDT', ['BTC'], 1.0, 0.0)
    assert res is True
    assert records[0]['accepted'] is True
    assert records[0]['orderId'] == '1'
    assert calls['accept'] == 1


def test_not_accepted_without_success(monkeypatch):
    monkeypatch.setenv('PAPER', '0')
    monkeypatch.setenv('ENABLE_LIVE', '1')
    quote = {
        'quoteId': 'q2',
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

    def fake_log(quote_data, accepted, order_id, error, create_time, dry_run, order_status=None, mode=None, edge=None, region=None):
        records.append({'accepted': accepted, 'orderId': order_id})

    monkeypatch.setattr(convert_cycle, 'log_conversion_result', fake_log)
    monkeypatch.setattr(convert_cycle, 'accept_quote', lambda qid: {'orderId': '1', 'createTime': 2})
    monkeypatch.setattr(convert_cycle, 'get_order_status', lambda **k: {'orderStatus': 'FAIL'})
    res = convert_cycle.process_pair('USDT', ['BTC'], 1.0, 0.0)
    assert res is False
    assert records[0]['accepted'] is False


def test_skip_expired_quote(monkeypatch):
    setup_env(monkeypatch)
    monkeypatch.setattr(convert_cycle, 'reset_cycle', lambda: None)
    monkeypatch.setattr(convert_cycle, 'should_throttle', lambda *a, **k: False)
    monkeypatch.setattr(convert_cycle, 'filter_top_tokens', lambda tokens, score_threshold, top_n=2: list(tokens.items()))

    current = 1000
    monkeypatch.setattr(convert_api, '_current_timestamp', lambda: current)

    expired_quote = {
        'quoteId': 'q3',
        'ratio': 1.0,
        'inverseRatio': 1.0,
        'fromAmount': 1.0,
        'toAmount': 1.0,
        'score': 1.0,
        'validTimestamp': current - 1,
    }

    monkeypatch.setattr(convert_cycle, 'get_quote', lambda *a, **k: expired_quote)
    calls = {'accept': 0}

    def fake_accept(qid):
        calls['accept'] += 1
        return {'dryRun': True}

    monkeypatch.setattr(convert_cycle, 'accept_quote', fake_accept)
    monkeypatch.setattr(convert_cycle, 'log_conversion_result', lambda *a, **k: None)

    res = convert_cycle.process_pair('USDT', ['BTC'], 1.0, 0.0)
    assert res is False
    assert calls['accept'] == 0
