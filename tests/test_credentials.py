import importlib
import sys
import types


def _setup_cfg(monkeypatch, key="k", secret="s"):
    cfg = types.SimpleNamespace(
        BINANCE_API_KEY=key,
        BINANCE_API_SECRET=secret,
        OPENAI_API_KEY="",
        TELEGRAM_TOKEN="",
        CHAT_ID="",
        DEV3_PAPER_MODE=True,
        DEV3_REGION_TIMER="ASIA",
        DEV3_RECV_WINDOW_MS=5000,
    )
    monkeypatch.setitem(sys.modules, "config_dev3", cfg)


def test_credentials_from_config(monkeypatch):
    _setup_cfg(monkeypatch, key="file-key", secret="file-secret")
    import convert_api
    importlib.reload(convert_api)
    assert convert_api.BINANCE_API_KEY == "file-key"
    assert convert_api.BINANCE_API_SECRET == "file-secret"


def test_no_keys_in_logs(monkeypatch, caplog):
    _setup_cfg(monkeypatch)
    import convert_api
    monkeypatch.setattr(convert_api, "_time_synced", True)

    class Sess:
        def __init__(self):
            self.calls = 0

        def post(self, url, data=None, headers=None, timeout=None, params=None):
            self.calls += 1

            class R:
                status_code = 200
                headers = {}

                def json(inner_self):
                    if self.calls == 1:
                        return {"code": -1003, "msg": "oops"}
                    return {}

            return R()

    sess = Sess()
    monkeypatch.setattr(convert_api, "_session", sess)
    monkeypatch.setattr(
        convert_api,
        "time",
        type("T", (), {"sleep": lambda s: None, "time": lambda: 0}),
    )
    monkeypatch.setattr(convert_api, "random", type("R", (), {"uniform": lambda a, b: 0}))
    monkeypatch.setattr(convert_api, "get_current_timestamp", lambda: 0)

    with caplog.at_level("WARNING"):
        convert_api._request("POST", "/sapi/v1/convert/getQuote", {"a": 1})

    assert "file-key" not in caplog.text
    assert "file-secret" not in caplog.text

