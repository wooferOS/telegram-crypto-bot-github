import json
from pathlib import Path

import os
import sys
import threading

sys.path.insert(0, os.getcwd())

import top_tokens_utils as ttu


def test_atomic_write_and_read(tmp_path):
    path = tmp_path / "tokens.json"
    data = {
        "version": ttu.TOP_TOKENS_VERSION,
        "region": "ASIA",
        "generated_at": 0,
        "pairs": [{"from": "USDT", "to": "BTC", "score": 1.0, "edge": 0.1}],
    }
    ttu.write_top_tokens_atomic(str(path), data)
    read = ttu.read_top_tokens(str(path))
    assert read == data


def test_concurrent_writes(tmp_path):
    path = tmp_path / "c.json"
    data1 = {
        "version": ttu.TOP_TOKENS_VERSION,
        "region": "ASIA",
        "generated_at": 1,
        "pairs": [{"from": "USDT", "to": "BTC", "score": 1, "edge": 0.1}],
    }
    data2 = {
        "version": ttu.TOP_TOKENS_VERSION,
        "region": "ASIA",
        "generated_at": 2,
        "pairs": [{"from": "USDT", "to": "ETH", "score": 2, "edge": 0.2}],
    }

    t1 = threading.Thread(target=ttu.write_top_tokens_atomic, args=(str(path), data1))
    t2 = threading.Thread(target=ttu.write_top_tokens_atomic, args=(str(path), data2))
    t1.start(); t2.start(); t1.join(); t2.join()
    final = ttu.read_top_tokens(str(path))
    assert final in (data1, data2)

