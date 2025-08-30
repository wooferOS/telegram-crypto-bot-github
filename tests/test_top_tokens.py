import json
from pathlib import Path

import os
import sys

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


def test_migration_and_validation(tmp_path):
    legacy = tmp_path / "legacy.json"
    with open(legacy, "w", encoding="utf-8") as f:
        json.dump([{"from": "USDT", "to": "ETH"}], f)

    migrated = ttu.read_top_tokens(str(legacy))
    assert migrated["version"] == ttu.TOP_TOKENS_VERSION
    assert migrated["pairs"][0]["from"] == "USDT"
    assert ttu.validate_schema(migrated)

