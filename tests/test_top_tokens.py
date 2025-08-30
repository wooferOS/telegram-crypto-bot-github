import json
from pathlib import Path

import os
import sys

sys.path.insert(0, os.getcwd())

import top_tokens_utils as ttu


def test_migration_and_fallback(tmp_path):
    ttu.LOGS_DIR = str(tmp_path)
    legacy_path = Path(tmp_path) / 'top_tokens.asia.json'
    with open(legacy_path, 'w', encoding='utf-8') as f:
        json.dump([{"from": "USDT", "to": "BTC"}], f)
    data = ttu.load_top_tokens('ASIA')
    assert data['version'] == ttu.TOP_TOKENS_VERSION
    assert data['pairs'][0]['from'] == 'USDT'

    # remove file to trigger fallback
    legacy_path.unlink()
    data = ttu.load_top_tokens('ASIA')
    assert data['pairs']
    assert Path(ttu.LOGS_DIR, 'top_tokens.asia.json').exists()
