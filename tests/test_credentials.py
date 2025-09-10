import importlib
import sys
from pathlib import Path


def _setup_cfg(monkeypatch, tmp_path: Path, key="k", secret="s"):
    cfg = tmp_path / "config_dev3.py"
    cfg.write_text(
        f"""
BINANCE_API_KEY = '{key}'
BINANCE_API_SECRET = '{secret}'
OPENAI_API_KEY = ''
TELEGRAM_TOKEN = ''
CHAT_ID = ''
DEV3_REGION_TIMER = 'ASIA'
DEV3_RECV_WINDOW_MS = 5000
DEV3_RECV_WINDOW_MAX_MS = 60000
API_BASE = 'https://api.binance.com'
MARKETDATA_BASE = 'https://data-api.binance.vision'
SCORING_WEIGHTS = {{'edge': 1.0, 'liquidity': 0.1, 'momentum': 0.1, 'spread': 0.1, 'volatility': 0.1}}
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("config_dev3", None)


def test_credentials_from_config(monkeypatch, tmp_path):
    _setup_cfg(monkeypatch, tmp_path, key="file-key", secret="file-secret")
    import convert_api
    importlib.reload(convert_api)
    assert convert_api.BINANCE_API_KEY == "file-key"
    assert convert_api.BINANCE_API_SECRET == "file-secret"


def test_no_keys_in_logs(monkeypatch, caplog, tmp_path):
    _setup_cfg(monkeypatch, tmp_path)
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

