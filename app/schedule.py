"""Weekday auto session; mock outside the cash window.

Paper month: arms paper+auto ~09:10 IST. Never arms live while DESK_LIVE_ENABLED=0.
After client confirmation: set DESK_LIVE_ENABLED=1 (+ LIVE_NIFTY/LIVE_BANKNIFTY=1) and
restart — the same weekday clock then arms live+auto. Process boot is still STOPPED;
this tick is what arms the session. Kill switch still wins.

Stop from the UI pauses only for the rest of that IST day.
After 15:45 disarm, mock is armed again for testing.
"""
from __future__ import annotations

import os
from uuid import uuid4

from app.auth import get_settings
from app.mock import MOCK
from app.runners.state import RUNNER, _now
from app.session import market_session, now_ist, session_day

# Match the trader UI (5x). 60x finishes the tape in ~6 minutes and looks "stopped".
_MOCK_SPEED = 5.0
_operator_hold_mock = False


def env_paper_auto() -> bool:
    return os.environ.get("DESK_PAPER_AUTO", "").strip().lower() in ("1", "true", "yes")


def paper_only() -> bool:
    """When set, never fall back to mock replay — paper+auto only."""
    return os.environ.get("DESK_PAPER_ONLY", "").strip().lower() in ("1", "true", "yes")


def schedule_wanted() -> bool:
    return env_paper_auto() or bool(getattr(RUNNER, "paper_auto_schedule", False))


def paused_today() -> bool:
    return str(getattr(RUNNER, "paused_day", "") or "") == session_day().isoformat()


def in_cash_window() -> bool:
    now = now_ist()
    if now.weekday() >= 5:
        return False
    sess = market_session()
    if sess in ("pre", "open"):
        return now.hour > 9 or (now.hour == 9 and now.minute >= 10)
    # Keep armed through 15:45 for EOD flatten
    return now.hour == 15 and now.minute <= 45


def _live_cutover_ready() -> bool:
    """True when master live is on and at least one book flag is on (per-book G5 still gates place)."""
    s = get_settings()
    return bool(s.live_enabled and (s.live_nifty or s.live_banknifty))


def _discard_mock() -> None:
    if (RUNNER.mode or "").lower() != "mock":
        return
    try:
        MOCK.exclusive_sync(MOCK.discard)
    except Exception:
        pass


def arm_paper_auto(*, reason: str) -> None:
    if RUNNER.kill.active:
        return
    already = RUNNER.trading_active() and (RUNNER.mode or "").lower() == "paper" and (RUNNER.execution or "") == "auto"
    _discard_mock()
    RUNNER.state = "RUNNING"
    RUNNER.mode = "paper"
    RUNNER.execution = "auto"
    RUNNER.stop_requested = False
    RUNNER.paper_auto_schedule = True
    RUNNER.last_error = None
    RUNNER.replay_day = None
    if not already:
        RUNNER.task_id = uuid4().hex[:12]
        RUNNER.started_at = _now()
        from app import auto_engine

        auto_engine.load_persisted()
        RUNNER.audit_event("trading.schedule_arm", reason=reason, operator_id="schedule", mode="paper")
    RUNNER.persist()


def arm_live_auto(*, reason: str) -> None:
    """Same weekday clock as paper. Only after DESK_LIVE_ENABLED + both book flags."""
    if RUNNER.kill.active:
        return
    if not _live_cutover_ready():
        arm_paper_auto(reason=reason)
        return
    already = RUNNER.trading_active() and (RUNNER.mode or "").lower() == "live" and (RUNNER.execution or "") == "auto"
    _discard_mock()
    RUNNER.state = "RUNNING"
    RUNNER.mode = "live"
    RUNNER.execution = "auto"
    RUNNER.stop_requested = False
    RUNNER.paper_auto_schedule = True
    RUNNER.last_error = None
    RUNNER.replay_day = None
    if not already:
        RUNNER.task_id = uuid4().hex[:12]
        RUNNER.started_at = _now()
        from app import auto_engine

        auto_engine.load_persisted()
        RUNNER.audit_event("trading.schedule_arm", reason=reason, operator_id="schedule", mode="live")
    RUNNER.persist()


def hold_mock() -> None:
    """UI Stop in mock: do not auto-rearm until Start (so Stop is testable)."""
    global _operator_hold_mock
    _operator_hold_mock = True


def release_mock_hold() -> None:
    global _operator_hold_mock
    _operator_hold_mock = False


def arm_mock(*, reason: str) -> None:
    """Sim replay for testing. Same auto/manual rules as live, no broker APIs."""
    if RUNNER.kill.active:
        return
    if (RUNNER.mode or "").lower() == "live" and RUNNER.trading_active():
        return
    if _operator_hold_mock:
        return
    already = RUNNER.trading_active() and (RUNNER.mode or "").lower() == "mock" and MOCK.loaded
    if already:
        return
    replay = MOCK.exclusive_sync(lambda: MOCK.start(execution="auto", speed=_MOCK_SPEED))
    RUNNER.state = "RUNNING"
    RUNNER.mode = "mock"
    RUNNER.execution = "auto"
    RUNNER.stop_requested = False
    RUNNER.last_error = None
    RUNNER.replay_day = replay.get("day")
    RUNNER.speed = _MOCK_SPEED
    RUNNER.task_id = uuid4().hex[:12]
    RUNNER.started_at = _now()
    RUNNER.persist()
    RUNNER.audit_event("trading.schedule_mock", reason=reason, operator_id="schedule")


def disarm(*, reason: str) -> None:
    if not RUNNER.trading_active():
        return
    if (RUNNER.mode or "").lower() not in ("paper", "live"):
        return
    try:
        from app import paper_archive

        paper_archive.capture(reason=reason)
    except Exception:
        pass
    RUNNER.stop_requested = True
    RUNNER.state = "STOPPED"
    RUNNER.persist()
    RUNNER.audit_event("trading.schedule_stop", reason=reason, operator_id="schedule", mode=RUNNER.mode)


def pause_today() -> None:
    RUNNER.paused_day = session_day().isoformat()
    RUNNER.persist()


def tick() -> None:
    if RUNNER.kill.active:
        return
    if not schedule_wanted():
        return
    if in_cash_window():
        if paused_today():
            return
        if (RUNNER.mode or "").lower() == "live" and RUNNER.trading_active():
            return
        if _live_cutover_ready():
            arm_live_auto(reason="nse_cash_window")
        else:
            arm_paper_auto(reason="nse_cash_window")
        return
    if RUNNER.trading_active() and (RUNNER.mode or "").lower() in ("paper", "live"):
        disarm(reason="session_end")
        if not paper_only():
            arm_mock(reason="after_cash_window")
        return
    # Weekend / after hours: keep mock available for testing (Dhan positions stay).
    if paper_only():
        return
    if _operator_hold_mock:
        return
    if (RUNNER.mode or "").lower() == "live" and RUNNER.trading_active():
        return
    if not RUNNER.trading_active():
        arm_mock(reason="outside_cash_window")
