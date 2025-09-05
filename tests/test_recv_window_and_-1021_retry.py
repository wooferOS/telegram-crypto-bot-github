import sys
import os
import types

os.environ.setdefault("BINANCE_API_KEY", "k")
os.environ.setdefault("BINANCE_API_SECRET", "s")
sys.modules.setdefault(
    "config_dev3", types.SimpleNamespace(TELEGRAM_CHAT_ID="", TELEGRAM_TOKEN="")
)

sys.path.insert(0, os.getcwd())

import convert_api


class Resp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_recv_window_and_retry(monkeypatch):
    sent = []

    def record_post(url, data=None, headers=None, timeout=10):
        sent.append(data)
        return Resp({})

    def record_get(url, params=None, headers=None, timeout=10):
        sent.append(params)
        if "tradeFlow" in url:
            return Resp({"list": []})
        return Resp({"orderStatus": "SUCCESS"})

    monkeypatch.setattr(convert_api._session, "post", record_post)
    monkeypatch.setattr(convert_api._session, "get", record_get)
    convert_api._time_synced = True

    convert_api.get_quote_with_id("A", "B", from_amount=1.0)
    convert_api.accept_quote("qid")
    convert_api.get_order_status(orderId="1")
    convert_api.trade_flow(startTime=1, endTime=2)

    for p in sent:
        assert p["recvWindow"] == convert_api.DEFAULT_RECV_WINDOW
        assert "timestamp" in p

    calls = {"n": 0}
    sync_calls = []
    sleeps = []

    def fake_get(url, params=None, headers=None, timeout=10):
        calls["n"] += 1
        if calls["n"] == 1:
            return Resp({"code": -1021, "msg": "clock"})
        return Resp({"orderStatus": "SUCCESS"})

    monkeypatch.setattr(convert_api._session, "get", fake_get)
    monkeypatch.setattr(convert_api, "_sync_time", lambda: sync_calls.append(1))
    monkeypatch.setattr(convert_api.time, "sleep", lambda s: sleeps.append(s))
    convert_api._time_synced = True

    convert_api.get_order_status(orderId="1")

    assert calls["n"] == 2
    assert len(sync_calls) == 1
    assert sleeps and sleeps[0] > 0
