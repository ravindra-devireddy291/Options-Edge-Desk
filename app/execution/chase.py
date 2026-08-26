"""Limit chase loop — modify working entry/exit until fill or timeout."""
from __future__ import annotations

import time
from typing import Optional

from app.brokers.dhan import client as dhan
from app.execution.armor import resolve_depth
from app.execution.config import ARMOR
from app.execution.spread_chaser import next_limit_price
from app.execution.sessions import all_open, sync_protective_legs
from app.execution.types import SessionState


def _chase_timeout(session) -> None:
    oid = session.entry_order_id
    if oid and session.state in (SessionState.ENTRY_WORKING, SessionState.ENTRY_PARTIAL):
        try:
            dhan.cancel_order(oid)
        except Exception:
            pass
    role = str(session.meta.get("leg_role") or "entry")
    if session.filled_qty > 0 and role == "entry":
        sync_protective_legs(session, session.filled_qty, session.avg_entry_px)
        session.state = SessionState.IN_POSITION
        session.meta["chase_timed_out"] = True
    elif session.filled_qty > 0 and role == "exit":
        session.state = SessionState.IN_POSITION
        session.exit_reason = "exit_partial_chase_timeout"
    else:
        session.state = SessionState.ABORTED
        session.exit_reason = "chase_timeout"


def run_chase_cycle() -> int:
    """Modify open limit legs toward market. Returns number of modifies attempted."""
    if not ARMOR.enabled:
        return 0
    now = time.time()
    modified = 0
    for session in all_open():
        if session.state not in (SessionState.ENTRY_WORKING, SessionState.ENTRY_PARTIAL):
            continue
        if not session.entry_order_id:
            continue

        deadline = float(session.meta.get("chase_deadline_ts") or 0)
        if deadline and now > deadline:
            _chase_timeout(session)
            continue

        depth, _refuse, _ws = resolve_depth(session.security_id)
        if depth is None:
            continue

        role = str(session.meta.get("leg_role") or "entry")
        side = "sell" if role == "exit" else "buy"
        ref = session.limit_px or session.avg_entry_px or depth.mid
        chase = next_limit_price(depth, ARMOR, ref_px=ref, side=side)
        if chase.refused:
            continue

        remaining = max(0, int(session.requested_qty) - int(session.filled_qty))
        if remaining <= 0:
            continue

        tick = float(ARMOR.tick_size)
        if abs(chase.limit_px - session.limit_px) < tick * 0.5:
            continue

        try:
            dhan.modify_order(
                session.entry_order_id,
                quantity=remaining,
                price=chase.limit_px,
                order_type="LIMIT",
            )
            session.limit_px = chase.limit_px
            session.meta["last_chase_ts"] = now
            modified += 1
        except Exception:
            session.meta["last_chase_error"] = True

    return modified
