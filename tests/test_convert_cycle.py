import os
import sys
import types

sys.path.insert(0, os.getcwd())

import convert_api
import convert_cycle

sys.modules.setdefault(
    'config_dev3',
    types.SimpleNamespace(
        BINANCE_API_KEY='k',
        BINANCE_API_SECRET='s',
        OPENAI_API_KEY='',
        TELEGRAM_TOKEN='',
        CHAT_ID='',
        DEV3_REGION_TIMER='ASIA',
        DEV3_RECV_WINDOW_MS=5000,
        DEV3_RECV_WINDOW_MAX_MS=60000,
        API_BASE="https://api.binance.com",
        MARKETDATA_BASE="https://data-api.binance.vision",
        SCORING_WEIGHTS={"edge": 1.0, "liquidity": 0.1, "momentum": 0.1, "spread": 0.1, "volatility": 0.1},
    ),
)


def setup_env(monkeypatch):
    monkeypatch.setattr(convert_cycle, 'check_risk', lambda: (0, 0))
    monkeypatch.setattr(
        convert_cycle,
        'scoring',
        types.SimpleNamespace(score_pair=lambda f, t, r: {'edge': 0.0, 'score': r}),
    )
    monkeypatch.setattr(convert_cycle, 'log_cycle_summary', lambda: None)
    monkeypatch.setattr(convert_cycle, 'set_cycle_limit', lambda limit: None)
    monkeypatch.setattr(convert_cycle, 'load_symbol_filters', lambda *a, **k: (None, None, None))
    monkeypatch.setattr(convert_cycle, 'get_last_price_usdt', lambda *a, **k: None)


def test_process_pair_success(monkeypatch):
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

    def fake_log(quote_data, accepted, order_id, error, create_time, order_status=None, edge=None, region=None, step_size=None, min_notional=None, px=None, est_notional=None, reason=None):
        records.append({'accepted': accepted, 'orderId': order_id})

    monkeypatch.setattr(convert_cycle, 'log_conversion_result', fake_log)
    monkeypatch.setattr(convert_cycle, 'accept_quote', lambda qid: {'orderId': '1', 'createTime': 2})
    monkeypatch.setattr(convert_cycle, 'get_order_status', lambda **k: {'orderStatus': 'SUCCESS'})

    res = convert_cycle.process_pair('USDT', ['BTC'], 1.0, 0.0)
    assert res is True
    assert records[0]['accepted'] is True
    assert records[0]['orderId'] == '1'


def test_not_accepted_without_success(monkeypatch):
    setup_env(monkeypatch)
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

    def fake_log(quote_data, accepted, order_id, error, create_time, order_status=None, edge=None, region=None, step_size=None, min_notional=None, px=None, est_notional=None, reason=None):
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
        return {'orderId': '1', 'createTime': 2}

    monkeypatch.setattr(convert_cycle, 'accept_quote', fake_accept)
    monkeypatch.setattr(convert_cycle, 'log_conversion_result', lambda *a, **k: None)

    res = convert_cycle.process_pair('USDT', ['BTC'], 1.0, 0.0)
    assert res is False
    assert calls['accept'] == 0
