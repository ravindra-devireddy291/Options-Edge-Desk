"""Trailing stop math — matches edge_lab gap_continuation (peak mode)."""
from __future__ import annotations


def floor_stop_px(entry_px: float, stop_pct: float) -> float:
    if entry_px <= 0:
        return 0.0
    return entry_px * (1.0 - float(stop_pct))


def trail_active(entry_px: float, peak_px: float, trail_activate_pct: float) -> bool:
    if entry_px <= 0 or trail_activate_pct <= 0:
        return False
    return (peak_px - entry_px) / entry_px >= float(trail_activate_pct)


def effective_stop_px(
    *,
    entry_px: float,
    peak_px: float,
    stop_pct: float,
    trail_pct: float,
    trail_activate_pct: float,
) -> float:
    floor_px = floor_stop_px(entry_px, stop_pct)
    if trail_pct <= 0 or not trail_active(entry_px, peak_px, trail_activate_pct):
        return floor_px
    trail_px = peak_px * (1.0 - float(trail_pct))
    return max(floor_px, trail_px)


def sl_trigger_from_stop(stop_px: float, tick_size: float) -> float:
    return round(float(stop_px) + float(tick_size), 2)
