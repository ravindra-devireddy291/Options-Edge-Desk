"""REST poll fallback when order-update WS misses events."""
from __future__ import annotations

from app.brokers.dhan import client as dhan
from app.execution.sessions import all_open, handle_order_update
from app.execution.types import DhanOrderUpdate


def reconcile_open_sessions() -> int:
    """Poll broker for open session legs. Returns updates applied."""
    applied = 0
    for session in all_open():
        for oid in (
            session.entry_order_id,
            session.sl_order_id,
            session.tp_order_id,
        ):
            if not oid:
                continue
            try:
                raw = dhan.get_order(str(oid))
            except Exception:
                continue
            if not raw:
                continue
            upd = DhanOrderUpdate.from_rest(raw)
            if not upd.order_id:
                upd.order_id = str(oid)
            if handle_order_update(upd):
                applied += 1
    return applied
