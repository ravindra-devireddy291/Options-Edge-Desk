"""Weekday paper-auto session; mock outside the cash window.

Never arms live. Stop from the UI pauses paper only for the rest of that IST day.
Mock running overnight does not block Monday ~09:10 paper-auto.
After 15:45 paper disarm, mock is armed again for testing.
"""
from __future__ import annotations

import os
from uuid import uuid4

from app.mock import MOCK
from app.runners.state import RUNNER, _now
from app.session import market_session, now_ist, session_day

_MOCK_SPEED = 60.0


def env_paper_auto() -> bool:
    return os.environ.get("DESK_PAPER_AUTO", "").strip().lower() in ("1", "true", "yes")


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


def arm_paper_auto(*, reason: str) -> None:
    if RUNNER.kill.active:
        return
    already = RUNNER.trading_active() and (RUNNER.mode or "").lower() == "paper" and (RUNNER.execution or "") == "auto"
    if (RUNNER.mode or "").lower() == "mock":
        try:
            MOCK.exclusive_sync(MOCK.discard)
        except Exception:
            pass
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
        RUNNER.audit_event("trading.schedule_arm", reason=reason, operator_id="schedule")
    RUNNER.persist()


def arm_mock(*, reason: str) -> None:
    """Sim replay for testing. Same auto/manual rules as live, no broker APIs."""
    if RUNNER.kill.active:
        return
    if (RUNNER.mode or "").lower() == "live" and RUNNER.trading_active():
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
    if (RUNNER.mode or "").lower() != "paper":
        return
    RUNNER.stop_requested = True
    RUNNER.state = "STOPPED"
    RUNNER.persist()
    RUNNER.audit_event("trading.schedule_stop", reason=reason, operator_id="schedule")


def pause_today() -> None:
    RUNNER.paused_day = session_day().isoformat()
    RUNNER.persist()


def tick() -> None:
    if RUNNER.kill.active:
        return
    if (RUNNER.mode or "").lower() == "live" and RUNNER.trading_active():
        return
    if not schedule_wanted():
        return
    if in_cash_window():
        if paused_today():
            return
        arm_paper_auto(reason="nse_cash_window")
        return
    if RUNNER.trading_active() and (RUNNER.mode or "").lower() == "paper":
        disarm(reason="session_end")
        arm_mock(reason="after_cash_window")
        return
    # Weekend / after hours: keep mock available for testing (paper stays untouched at Dhan).
    if not RUNNER.trading_active():
        arm_mock(reason="outside_cash_window")
