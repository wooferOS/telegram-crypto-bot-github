import os
import sys

import types
import convert_model


def test_predict_fallback(monkeypatch):
    # simulate missing model
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    quote = {"ratio": 1.1}
    expected_profit, prob_up, score = convert_model.predict("A", "B", quote)
    assert expected_profit != 0
    assert prob_up == 0.5
    assert score == expected_profit * prob_up
