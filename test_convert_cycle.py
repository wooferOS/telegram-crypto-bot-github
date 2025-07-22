import json
import logging
import types
import sys
from datetime import datetime


def test_cyclic_fallback_skip(tmp_path, monkeypatch, caplog):
    # Provide dummy config for convert_api
    sys.modules["config_dev3"] = types.SimpleNamespace(
        BINANCE_API_KEY="key",
        BINANCE_SECRET_KEY="secret",
        TELEGRAM_CHAT_ID="0",
        TELEGRAM_TOKEN="token",
    )
    # Import module after setting up dummy config
    import importlib

    convert_cycle = importlib.import_module("convert_cycle")

    hist_path = tmp_path / "fallback_history.json"
    history = {
        "last_from": "BTTC",
        "last_to": "PEPE",
        "timestamp": datetime.utcnow().isoformat(),
    }
    hist_path.write_text(json.dumps(history))
    monkeypatch.setattr(convert_cycle, "FALLBACK_HISTORY_PATH", str(hist_path))

    called = []

    def fake_try_convert(from_token: str, to_token: str, amount: float, score: float):
        called.append((from_token, to_token, amount, score))
        return True

    monkeypatch.setattr(convert_cycle, "try_convert", fake_try_convert)

    pairs = [{"from_token": "PEPE", "to_token": "BTTC", "score": 0.1}]
    balances = {"PEPE": 50.0}

    with caplog.at_level(logging.WARNING):
        convert_cycle.fallback_convert(pairs, balances)

    assert not called
    assert "Виявлено циклічну конверсію" in caplog.text
