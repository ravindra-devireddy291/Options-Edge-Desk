"""Accelerated NSE-session clock for mock replay."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from app.session import IST, SESSION_CLOSE, SESSION_OPEN, market_session, to_utc_z

DEFAULT_SPEED = 60.0
SESSION_OPEN_DT = SESSION_OPEN
SESSION_CLOSE_DT = SESSION_CLOSE


def _combine(day: date, t: time) -> datetime:
    return datetime(day.year, day.month, day.day, t.hour, t.minute, t.second, tzinfo=IST)


@dataclass
class SimClock:
    day: date
    speed: float = DEFAULT_SPEED
    playing: bool = False
    wall_started: float = 0.0
    sim_anchor: Optional[datetime] = None
    frozen: Optional[datetime] = None

    def session_open(self) -> datetime:
        return _combine(self.day, SESSION_OPEN)

    def session_close(self) -> datetime:
        return _combine(self.day, SESSION_CLOSE)

    def reset(self, day: date, speed: float = DEFAULT_SPEED) -> None:
        import time as _time

        self.day = day
        self.speed = max(1.0, float(speed))
        self.playing = True
        self.wall_started = _time.monotonic()
        self.sim_anchor = self.session_open()
        self.frozen = None

    def pause(self) -> None:
        if self.playing:
            self.frozen = self.now()
        self.playing = False

    def now(self) -> datetime:
        if not self.playing or self.sim_anchor is None:
            return self.frozen or self.session_open()
        import time as _time

        elapsed = max(0.0, _time.monotonic() - self.wall_started)
        sim = self.sim_anchor + timedelta(seconds=elapsed * self.speed)
        close = self.session_close()
        if sim >= close:
            return close
        return sim

    def market_session(self) -> str:
        return market_session(self.now())

    def sim_time_iso(self) -> str:
        return to_utc_z(self.now())

    def snapshot(self) -> dict:
        now = self.now()
        return {
            "day": self.day.isoformat(),
            "speed": self.speed,
            "sim_time": to_utc_z(now),
            "playing": bool(self.playing and now < self.session_close()),
        }
