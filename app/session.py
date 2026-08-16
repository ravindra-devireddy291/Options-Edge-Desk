"""NSE cash session clock. JSON timestamps stay UTC; `day` is IST calendar date."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
SESSION_LABEL = "NSE 09:15–15:30 IST"


def now_ist() -> datetime:
    return datetime.now(IST)


def session_day(at: Optional[datetime] = None) -> date:
    """NSE cash session calendar date in IST."""
    dt = at.astimezone(IST) if at is not None else now_ist()
    return dt.date()


def market_session(at: Optional[datetime] = None) -> str:
    """pre | open | closed (weekends always closed)."""
    dt = at.astimezone(IST) if at is not None else now_ist()
    if dt.weekday() >= 5:
        return "closed"
    t = dt.time()
    if t < SESSION_OPEN:
        return "pre"
    if t <= SESSION_CLOSE:
        return "open"
    return "closed"


def to_utc_z(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
