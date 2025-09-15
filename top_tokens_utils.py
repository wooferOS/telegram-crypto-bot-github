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
avoid corruption. Only the ``v1`` schema is supported.
"""

from __future__ import annotations

import fcntl
import json
import os
from typing import Any, Dict, List


def _norm_region(region):
    if isinstance(region, str):
        return region
    if isinstance(region, dict):
        for k in ("region", "name", "value", "id"):
            v = region.get(k)
            if isinstance(v, str):
                return v
    return str(region)

LOGS_DIR = "logs"
TOP_TOKENS_VERSION = "v1"


def read_top_tokens(path: str) -> Dict[str, Any]:
    """Read and validate top tokens from ``path``."""

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if (
        not isinstance(data, dict)
        or data.get("version") != TOP_TOKENS_VERSION
        or not isinstance(data.get("pairs"), list)
    ):
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
