import json
import os
import time
import fcntl
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

LOGS_DIR = "logs"
TOP_TOKENS_VERSION = 1
DEFAULT_TOPS = [{"from": "USDT", "to": "BTC"}, {"from": "USDT", "to": "ETH"}]


def _file_path(region: str) -> str:
    filename = f"top_tokens.{region.lower()}.json"
    return os.path.join(LOGS_DIR, filename)


def _validate(data: Dict[str, object]) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("version") != TOP_TOKENS_VERSION:
        return False
    if "region" not in data or "generated_at" not in data:
        return False
    if not isinstance(data.get("pairs"), list):
        return False
    for p in data["pairs"]:
        if not isinstance(p, dict):
            return False
        if "from" not in p or "to" not in p:
            return False
    return True


def _migrate(raw: object, region: str) -> Dict[str, object]:
    """Migrate legacy formats (list or dict without version)."""
    if isinstance(raw, dict) and raw.get("version") == TOP_TOKENS_VERSION:
        return raw
    pairs: List[Dict[str, object]] = []
    if isinstance(raw, list):
        pairs = [
            {"from": item.get("from") or item.get("from_token"),
             "to": item.get("to") or item.get("to_token"),
             "score": item.get("score"),
             "edge": item.get("edge")}
            for item in raw
            if isinstance(item, dict)
        ]
    elif isinstance(raw, dict) and "pairs" in raw:
        # old dict without version
        for item in raw.get("pairs", []):
            if isinstance(item, dict):
                pairs.append(item)
    else:
        pairs = DEFAULT_TOPS.copy()
    migrated = {
        "version": TOP_TOKENS_VERSION,
        "region": region.upper(),
        "generated_at": int(time.time() * 1000),
        "pairs": pairs,
    }
    return migrated


def load_top_tokens(region: str, create_if_missing: bool = True) -> Dict[str, object]:
    path = _file_path(region)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        data = {
            "version": TOP_TOKENS_VERSION,
            "region": region.upper(),
            "generated_at": int(time.time() * 1000),
            "pairs": DEFAULT_TOPS.copy(),
        }
        if create_if_missing:
            save_top_tokens(data, region)
        return data

    with open(path, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError:
            raw = DEFAULT_TOPS.copy()
    data = _migrate(raw, region)
    if not _validate(data):
        data = {
            "version": TOP_TOKENS_VERSION,
            "region": region.upper(),
            "generated_at": int(time.time() * 1000),
            "pairs": DEFAULT_TOPS.copy(),
        }
    return data


def save_top_tokens(data: Dict[str, object], region: Optional[str] = None) -> None:
    region = region or data.get("region", "ASIA")
    path = _file_path(region)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
        fcntl.flock(lock, fcntl.LOCK_UN)
