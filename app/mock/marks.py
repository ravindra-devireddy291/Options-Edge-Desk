"""Synthetic option marks: linear interpolate entry → exit over sim time."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


def lerp(a: float, b: float, t: float) -> float:
    t = max(0.0, min(1.0, t))
    return a + (b - a) * t


def progress(now: datetime, start: datetime, end: datetime) -> float:
    if end <= start:
        return 1.0 if now >= end else 0.0
    return (now - start).total_seconds() / (end - start).total_seconds()


def option_mark(ev: Dict[str, Any], now: datetime) -> float:
    entry = float(ev.get("entry") or 0)
    exit_px = float(ev.get("exit") or entry)
    t0 = ev["entry_at"]
    t1 = ev["exit_at"]
    if now <= t0:
        return round(entry, 4)
    if now >= t1:
        return round(exit_px, 4)
    return round(lerp(entry, exit_px, progress(now, t0, t1)), 4)


def index_spot(evs: list, underlying: str, now: datetime, fallback: float) -> Dict[str, Optional[float]]:
    rows = [e for e in evs if e.get("underlying") == underlying]
    if not rows:
        return {"ltp": fallback, "change_pct": 0.0, "change_pts": 0.0}
    # Dummy path around first strike so Home tape is never null.
    first = rows[0]
    strike = float(first.get("strike") or fallback)
    t0 = first["entry_at"]
    t1 = first["exit_at"]
    gap = float(first.get("gap_pts") or 50)
    open_px = strike - gap / 2.0
    close_px = strike + (gap / 2.0 if first.get("is_tp") else -gap / 4.0)
    if now <= t0:
        ltp = open_px
    elif now >= t1:
        ltp = close_px
    else:
        ltp = lerp(open_px, close_px, progress(now, t0, t1))
    chg = 0.0 if open_px == 0 else 100.0 * (ltp - open_px) / open_px
    pts = round(ltp - open_px, 2)
    return {"ltp": round(ltp, 2), "change_pct": round(chg, 4), "change_pts": pts}
