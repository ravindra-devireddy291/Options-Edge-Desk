"""Tick freshness gate."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union


def _as_utc(ts: Union[datetime, float, int]) -> datetime:
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        if ts > 1e18:
            return datetime.fromtimestamp(ts / 1e9, tz=timezone.utc)
        if ts > 1e12:
            return datetime.fromtimestamp(ts / 1e3, tz=timezone.utc)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    raise TypeError(type(ts))


def tick_age_ms(tick_ts: Union[datetime, float, int], *, now: Optional[datetime] = None) -> float:
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return max(0.0, (now_utc - _as_utc(tick_ts)).total_seconds() * 1000.0)


def tick_ok(tick_ts: Union[datetime, float, int], *, max_age_ms: int, now: Optional[datetime] = None) -> bool:
    return tick_age_ms(tick_ts, now=now) <= float(max_age_ms)
