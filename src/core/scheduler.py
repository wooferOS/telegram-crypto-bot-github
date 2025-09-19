"""Window helpers and simple file locking for auto-cycle."""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Dict

from config_dev3 import (
    ASIA_ANALYZE_FROM,
    ASIA_ANALYZE_TO,
    ASIA_TRADE_FROM,
    ASIA_TRADE_TO,
    JITTER_SEC,
    US_ANALYZE_FROM,
    US_ANALYZE_TO,
    US_TRADE_FROM,
    US_TRADE_TO,
)
from src.core import utils

_WINDOWS: Dict[str, Dict[str, str]] = {
    "asia": {
        "analyze_from": ASIA_ANALYZE_FROM,
        "analyze_to": ASIA_ANALYZE_TO,
        "trade_from": ASIA_TRADE_FROM,
        "trade_to": ASIA_TRADE_TO,
    },
    "us": {
        "analyze_from": US_ANALYZE_FROM,
        "analyze_to": US_ANALYZE_TO,
        "trade_from": US_TRADE_FROM,
        "trade_to": US_TRADE_TO,
    },
}

_LOCK_PATHS = {
    "asia": Path("/tmp/asia.lock"),
    "us": Path("/tmp/us.lock"),
}


def _get_window(region: str) -> Dict[str, str]:
    try:
        return _WINDOWS[region]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unknown region: {region}") from exc


def is_analyze_window(region: str) -> bool:
    window = _get_window(region)
    return utils.within_utc_window(window["analyze_from"], window["analyze_to"])


def is_trade_window(region: str) -> bool:
    window = _get_window(region)
    return utils.within_utc_window(window["trade_from"], window["trade_to"])


def jitter_start() -> float:
    """Sleep for the configured jitter and return the delay used."""
    return utils.sleep_jitter(JITTER_SEC)


@contextmanager
def acquire_lock(region: str):
    """Exclusive lock per region to prevent overlapping runs."""
    path = _LOCK_PATHS.get(region)
    if path is None:
        raise ValueError(f"Unknown region: {region}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise RuntimeError(f"Another process holds lock for {region}") from exc
    try:
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
