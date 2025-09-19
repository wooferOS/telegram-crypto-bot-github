"""Window helpers and jittered scheduling utilities."""
from __future__ import annotations

import fcntl
import logging
import os
import random
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from config_dev3 import ASIA_WINDOW, US_WINDOW

LOGGER = logging.getLogger(__name__)

_REGION_WINDOWS: Dict[str, object] = {
    "asia": ASIA_WINDOW,
    "us": US_WINDOW,
}

_LOCK_PATHS = {
    "asia": Path("/tmp/asia.lock"),
    "us": Path("/tmp/us.lock"),
}

_JITTER_RANGE = (120, 180)
_JITTER_CACHE: Dict[Tuple[str, str, datetime], datetime] = {}


@dataclass
class WindowDefinition:
    analyze: Tuple[time, time]
    trade: Tuple[time, time]


@dataclass
class WindowInterval:
    phase: str
    start: datetime
    end: datetime


def _coerce_time_pair(value: object) -> Tuple[time, time]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return _parse_time(value[0]), _parse_time(value[1])
    raise ValueError(f"Invalid window specification: {value!r}")


def _parse_time(value: object) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    raise ValueError(f"Invalid time value: {value!r}")


def _load_definition(region: str) -> WindowDefinition:
    raw = _REGION_WINDOWS.get(region)
    if raw is None:
        raise ValueError(f"Unknown region: {region}")

    analyze = getattr(raw, "analyze", None)
    trade = getattr(raw, "trade", None)
    if analyze is None and isinstance(raw, dict):
        analyze = raw.get("analyze")
    if trade is None and isinstance(raw, dict):
        trade = raw.get("trade")

    if analyze is None or trade is None:
        raise ValueError(f"Window configuration for {region} missing analyze/trade")

    return WindowDefinition(
        analyze=_coerce_time_pair(analyze),
        trade=_coerce_time_pair(trade),
    )


def _window_bounds(
    start_time: time,
    end_time: time,
    reference: datetime,
) -> Tuple[datetime, datetime]:
    start = datetime.combine(reference.date(), start_time, tzinfo=timezone.utc)
    end = datetime.combine(reference.date(), end_time, tzinfo=timezone.utc)
    if end <= start:
        end += timedelta(days=1)
    if reference < start - timedelta(days=1):
        start -= timedelta(days=1)
        end -= timedelta(days=1)
    elif reference >= end + timedelta(days=1):
        start += timedelta(days=1)
        end += timedelta(days=1)
    return start, end


def _jittered_start(region: str, phase: str, start: datetime, end: datetime) -> datetime:
    cache_key = (region, phase, start)
    jittered = _JITTER_CACHE.get(cache_key)
    if jittered is not None:
        return jittered

    jitter_min, jitter_max = _JITTER_RANGE
    offset = random.uniform(jitter_min, jitter_max)
    if random.choice((True, False)):
        offset *= -1
    jittered = start + timedelta(seconds=offset)
    if jittered >= end:
        jittered = end - timedelta(seconds=30)
    if jittered <= start - timedelta(seconds=60):
        jittered = start
    LOGGER.debug("Jittered start for %s/%s @ %s -> %s", region, phase, start, jittered)
    _JITTER_CACHE[cache_key] = jittered
    return jittered


def _build_interval(region: str, phase: str, now_utc: datetime) -> WindowInterval:
    definition = _load_definition(region)
    window = getattr(definition, phase)
    start, end = _window_bounds(window[0], window[1], now_utc)
    jittered_start = _jittered_start(region, phase, start, end)
    return WindowInterval(phase=phase, start=jittered_start, end=end)


def _find_active_interval(region: str, phase: str, now_utc: datetime) -> Optional[WindowInterval]:
    for delta in (-1, 0, 1):
        shifted_now = now_utc + timedelta(days=delta)
        interval = _build_interval(region, phase, shifted_now)
        if interval.start <= now_utc <= interval.end:
            return interval
    return None


def is_in_analyze_window(region: str, now_utc: datetime) -> bool:
    """Return ``True`` when ``now_utc`` is inside the jittered analyze window."""

    return _find_active_interval(region, "analyze", now_utc) is not None


def is_in_trade_window(region: str, now_utc: datetime) -> bool:
    """Return ``True`` when ``now_utc`` is inside the jittered trade window."""

    return _find_active_interval(region, "trade", now_utc) is not None


def next_window(region: str, now_utc: Optional[datetime] = None) -> WindowInterval:
    """Return the next analyze or trade window for ``region`` after ``now_utc``."""

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    candidates = []
    for phase in ("analyze", "trade"):
        interval = _build_interval(region, phase, now_utc)
        if now_utc <= interval.start:
            candidates.append(interval)
        else:
            next_day_interval = _build_interval(region, phase, now_utc + timedelta(days=1))
            candidates.append(next_day_interval)

    candidates.sort(key=lambda item: item.start)
    return candidates[0]


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
