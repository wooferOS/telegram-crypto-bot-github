import os
import sys

import convert_model


def test_predict_fallback(monkeypatch):
    # simulate missing model
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    quote = {"ratio": 1.1}
    expected_profit, prob_up, score = convert_model.predict("A", "B", quote)
    assert expected_profit != 0
    assert prob_up == 0.5
    assert score == expected_profit * prob_up


def test_train_convert_model_quiet(tmp_path, monkeypatch):
    os.makedirs("logs", exist_ok=True)
    import train_convert_model

    # use temporary files for history and logs
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(train_convert_model, "HISTORY_FILE", str(missing), raising=False)
    monkeypatch.setattr(train_convert_model, "LOG_FILE", str(tmp_path / "train.log"), raising=False)

    # run with missing file
    train_convert_model.main()

    # run with file missing required column
    hist = tmp_path / "history.json"
    hist.write_text("[{\"quoteId\": \"1\"}]")
    monkeypatch.setattr(train_convert_model, "HISTORY_FILE", str(hist), raising=False)
    train_convert_model.main()
