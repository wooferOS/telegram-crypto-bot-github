"""Market window helpers and locking primitives."""

from __future__ import annotations

import fcntl
import logging
import os
import random
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Tuple

from config_dev3 import ASIA_WINDOW, US_WINDOW


LOGGER = logging.getLogger(__name__)

_WINDOWS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "asia": ASIA_WINDOW,
    "us": US_WINDOW,
}

_LOCK_DIR = Path("/tmp")


def _parse_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    hour, minute = str(value).split(":", 1)
    return time(int(hour), int(minute))


def _window_bounds(window: Iterable[str | time], now_utc: datetime) -> Tuple[datetime, datetime]:
    start_raw, end_raw = list(window)
    start_time = _parse_time(start_raw)
    end_time = _parse_time(end_raw)
    start = datetime.combine(now_utc.date(), start_time, tzinfo=timezone.utc)
    end = datetime.combine(now_utc.date(), end_time, tzinfo=timezone.utc)
    if end <= start:
        end += timedelta(days=1)
    if now_utc < start and (start - now_utc) > timedelta(hours=12):
        start -= timedelta(days=1)
        end -= timedelta(days=1)
    elif now_utc > end and (now_utc - end) > timedelta(hours=12):
        start += timedelta(days=1)
        end += timedelta(days=1)
    return start, end


def in_window(region: str, phase: str, now_utc: datetime | None = None) -> bool:
    """Return True when ``now_utc`` falls inside the configured window."""

    now_utc = now_utc or datetime.now(timezone.utc)
    region = region.lower()
    phase = phase.lower()
    config = _WINDOWS.get(region)
    if config is None:
        raise ValueError(f"Unknown region {region}")
    window = config.get(phase)
    if window is None:
        raise ValueError(f"Window for {region}/{phase} is not configured")
    start, end = _window_bounds(window, now_utc)
    return start <= now_utc <= end


def sleep_with_jitter_before_phase(region: str, phase: str) -> None:
    """Sleep a random amount (120-180 seconds) before executing ``phase``."""

    delay = random.uniform(120, 180)
    LOGGER.info("Jitter before %s/%s: sleeping %.2fs", region, phase, delay)
    if delay > 0:
        from time import sleep

        sleep(delay)


@contextmanager
def single_instance_lock(name: str):
    """Exclusive lock implemented via ``fcntl`` on ``/tmp`` files."""

    lock_path = _LOCK_DIR / f"{name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:  # pragma: no cover - depends on runtime
        os.close(fd)
        raise RuntimeError(f"Another process holds lock {lock_path}") from exc

    try:
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
