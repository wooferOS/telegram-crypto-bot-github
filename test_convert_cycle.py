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


def test_learning_trade(monkeypatch):
    sys.modules["config_dev3"] = types.SimpleNamespace(
        BINANCE_API_KEY="key",
        BINANCE_SECRET_KEY="secret",
        TELEGRAM_CHAT_ID="0",
        TELEGRAM_TOKEN="token",
    )
    import importlib

    convert_cycle = importlib.import_module("convert_cycle")

    monkeypatch.setattr(convert_cycle, "get_balances", lambda: {"AAA": 10.0})
    monkeypatch.setattr(convert_cycle, "get_spot_price", lambda t: 1.0)
    monkeypatch.setattr(convert_cycle, "should_throttle", lambda f, t: False)
    monkeypatch.setattr(convert_cycle, "is_convertible_pair", lambda f, t: True)
    monkeypatch.setattr(convert_cycle, "get_min_convert_amount", lambda f, t: 0.0)
    monkeypatch.setattr(
        convert_cycle,
        "get_quote_with_retry",
        lambda f, t, a: {
            "fromAsset": f,
            "toAsset": t,
            "price": 1.0,
            "fromAmount": a,
            "toAmount": a + 0.1,
            "ratio": 1.1,
            "inverseRatio": 0.9,
        },
    )
    accepted = []

    def fake_accept_quote(q):
        accepted.append(q)
        return {"success": True, "fromAmount": q["fromAmount"], "toAmount": q["toAmount"]}

    monkeypatch.setattr(convert_cycle, "accept_quote", fake_accept_quote)
    monkeypatch.setattr(convert_cycle, "has_successful_trade", lambda token: False)
    monkeypatch.setattr(convert_cycle, "notify_success", lambda *a, **k: None)
    monkeypatch.setattr(convert_cycle, "notify_failure", lambda *a, **k: None)
    monkeypatch.setattr(convert_cycle, "notify_no_trade", lambda *a, **k: None)
    monkeypatch.setattr(convert_cycle, "notify_fallback_trade", lambda *a, **k: None)
    monkeypatch.setattr(convert_cycle, "save_convert_history", lambda *a, **k: None)
    messages = []
    monkeypatch.setattr(convert_cycle.convert_notifier, "send_telegram", lambda m: messages.append(m))

    pair = {
        "from_token": "AAA",
        "to_token": "BBB",
        "score": 0.0,
        "prob_up": 0.0,
        "forecast_count": 60,
    }

    convert_cycle.process_top_pairs([pair])

    assert accepted
    assert any("Навчальний трейд" in m for m in messages)
