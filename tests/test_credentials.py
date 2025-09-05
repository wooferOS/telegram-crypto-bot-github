import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.getcwd())


def _make_cfg(tmp_path: Path, key: str = "file-key", secret: str = "file-secret") -> Path:
    cfg = tmp_path / "cfg.py"
    cfg.write_text(
        f"BINANCE_API_KEY = '{key}'\nBINANCE_API_SECRET = '{secret}'\n",
        encoding="utf-8",
    )
    return cfg


def test_loads_from_file(monkeypatch, tmp_path):
    cfg = _make_cfg(tmp_path)
    monkeypatch.setenv("DEV_CONFIG_PATH", str(cfg))
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    import convert_api
    importlib.reload(convert_api)
    assert convert_api.BINANCE_API_KEY == "file-key"
    assert convert_api.BINANCE_API_SECRET == "file-secret"


def test_loads_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_API_KEY", "env-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "env-secret")
    monkeypatch.setenv("DEV_CONFIG_PATH", str(tmp_path / "missing.py"))
    import convert_api
    importlib.reload(convert_api)
    assert convert_api.BINANCE_API_KEY == "env-key"
    assert convert_api.BINANCE_API_SECRET == "env-secret"


def test_missing_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.setenv("DEV_CONFIG_PATH", str(tmp_path / "missing.py"))
    import convert_api
    with pytest.raises(RuntimeError):
        importlib.reload(convert_api)


def test_no_keys_in_logs(monkeypatch, caplog):
    import convert_api
    monkeypatch.setattr(convert_api, "BINANCE_API_KEY", "AKID1234")
    monkeypatch.setattr(convert_api, "BINANCE_API_SECRET", "SKID5678")
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

    assert "AKID1234" not in caplog.text
    assert "SKID5678" not in caplog.text

