from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_now(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def utc_ts(dt: datetime) -> int:
    return int(dt.timestamp())


def from_ts_utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def parse_hhmm(value: str) -> time:
    return time.fromisoformat(value)


def clamp_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def ensure_min_delay(dt: datetime, base: datetime, min_delay: timedelta) -> datetime:
    if dt < base + min_delay:
        return base + min_delay
    return dt
