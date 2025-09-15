"""Utilities for managing top token files.

The top tokens file stores conversion opportunities discovered during the
analysis phase.  Format (version ``v1``)::

    {
        "version": "v1",
        "region": "ASIA",
        "generated_at": 1700000000000,  # milliseconds
        "pairs": [
            {"from": "USDT", "to": "BTC", "score": 0.42, "edge": 0.1},
            ...
        ]
    }

Files are written atomically using a ``.lock`` file and temporary rename to
avoid corruption.  Legacy formats (plain list or dict without ``version``)
are migrated automatically when read.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import re


def _norm_region(region):
    if isinstance(region, str):
        return region
    if isinstance(region, dict):
        for k in ("region", "name", "value", "id"):
            v = region.get(k)
            if isinstance(v, str):
                return v
    return str(region)

import time
from typing import Any, Dict, List

LOGS_DIR = "logs"
TOP_TOKENS_VERSION = "v1"


# ---------------------------------------------------------------------------
# validation & migration
# ---------------------------------------------------------------------------


def validate_schema(data: Dict[str, Any]) -> bool:
    """Return ``True`` if ``data`` matches the expected schema."""

    if not isinstance(data, dict):
        return False
    if data.get("version") != TOP_TOKENS_VERSION:
        return False
    if not isinstance(data.get("region"), str):
        return False
    if "generated_at" not in data:
        return False
    pairs = data.get("pairs")
    if not isinstance(pairs, list):
        return False
    for item in pairs:
        if not isinstance(item, dict):
            return False
        # support both {asset: ...} and {from:..., to:...}
        if "asset" not in item and ("from" not in item or "to" not in item):
            return False
    return True


def _migrate_raw(raw: Any, region: str) -> Dict[str, Any]:
    """Convert legacy ``raw`` content to the new schema."""

    if isinstance(raw, dict) and raw.get("version") == TOP_TOKENS_VERSION:
        return raw

    pairs: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            pair: Dict[str, Any] = {}
            if "asset" in item:
                pair["asset"] = item["asset"]
            if "from" in item or "from_token" in item:
                pair["from"] = item.get("from", item.get("from_token"))
            if "to" in item or "to_token" in item:
                pair["to"] = item.get("to", item.get("to_token"))
            if "score" in item:
                pair["score"] = item.get("score")
            if "edge" in item:
                pair["edge"] = item.get("edge")
            if pair:
                pairs.append(pair)
    elif isinstance(raw, dict) and "pairs" in raw:
        for item in raw.get("pairs", []):
            if isinstance(item, dict):
                pairs.append(item)

    migrated = {
        "version": TOP_TOKENS_VERSION,
        "region": region.upper(),
        "generated_at": int(time.time() * 1000),
        "pairs": pairs,
    }
    return migrated


def migrate_legacy_if_needed(path: str) -> Dict[str, Any]:
    """Read file ``path`` and migrate legacy formats if required."""

    region = os.path.basename(path).split(".")[1].upper() if os.path.exists(path) else "ASIA"
    if not os.path.exists(path):
        return {
            "version": TOP_TOKENS_VERSION,
            "region": region,
            "generated_at": int(time.time() * 1000),
            "pairs": [],
        }

    with open(path, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError:
            raw = []
    return _migrate_raw(raw, region)


def read_top_tokens(path: str) -> Dict[str, Any]:
    """Read and validate top tokens from ``path``."""

    data = migrate_legacy_if_needed(path)
    if not validate_schema(data):
        raise ValueError("Invalid top tokens schema")
    return data


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


def write_top_tokens_atomic(path: str, data: Dict[str, Any]) -> None:
    """Atomically write ``data`` to ``path`` with file locking."""

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    lock_path = path + ".lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
        fcntl.flock(lock, fcntl.LOCK_UN)


# convenience helpers -------------------------------------------------------


def path_for_region(region: str) -> str:
    return os.path.join(LOGS_DIR, f"top_tokens.{_norm_region(region).lower()}.json")


def read_for_region(region: str) -> Dict[str, Any]:
    return read_top_tokens(path_for_region(region))


def save_for_region(data: Dict[str, Any], region: str | None = None) -> None:
    region = region or data.get("region", "ASIA")
    write_top_tokens_atomic(path_for_region(region), data)



def allowed_tos_for(from_token, region):
    """Повертає множину дозволених to-токенів для конкретного from_token.
    Джерело — ТІЛЬКИ v1-схема (data["pairs"]), фіати (isLegalMoney=True) відсікаються за даними Binance Capital."""
    from_token = str(from_token).upper()
    data = read_for_region(region)
    pairs = data.get("pairs", []) if isinstance(data, dict) else []
    tos = {
        str(item.get("to", "")).upper()
        for item in pairs
        if isinstance(item, dict)
        and str(item.get("from", "")).upper() == from_token
        and item.get("to")
    }
    # Мінусуємо всі фіати за Binance Capital (USER_DATA)
    try:
        from convert_cycle import _get_legal_money_set  # використовує підпис, як в API
        fiats = _get_legal_money_set(ttl_seconds=3600)
        if fiats:
            tos = {t for t in tos if t not in fiats}
    except Exception:
        # Якщо щось пішло не так з викликом — не розвалюємо пайплайн, захист ще є в convert_cycle
        pass
    return tos
