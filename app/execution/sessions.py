"""Managed session registry + partial-fill SL/TP sizing + OCO."""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from app.brokers.dhan import client as dhan
from app.execution.config import ARMOR
from app.execution.types import DhanOrderStatus, DhanOrderUpdate, ManagedSession, SessionState

_lock = threading.Lock()
_by_entry: Dict[str, ManagedSession] = {}
_by_sl: Dict[str, ManagedSession] = {}
_by_tp: Dict[str, ManagedSession] = {}
_by_correlation: Dict[str, ManagedSession] = {}


def register(session: ManagedSession) -> None:
    with _lock:
        if session.entry_order_id:
            _by_entry[session.entry_order_id] = session
        if session.sl_order_id:
            _by_sl[session.sl_order_id] = session
        if session.tp_order_id:
            _by_tp[session.tp_order_id] = session
        if session.correlation_id:
            _by_correlation[session.correlation_id] = session


def bind_entry_order_id(session: ManagedSession, order_id: str) -> None:
    session.entry_order_id = str(order_id)
    with _lock:
        _by_entry[session.entry_order_id] = session


def lookup(order_id: str = "", correlation_id: str = "") -> Optional[ManagedSession]:
    with _lock:
        if order_id and order_id in _by_entry:
            return _by_entry[order_id]
        if order_id:
            hit = _by_sl.get(order_id)
            if hit:
                return hit
            hit = _by_tp.get(order_id)
            if hit:
                return hit
        if correlation_id and correlation_id in _by_correlation:
            return _by_correlation[correlation_id]
    return None


def all_open() -> List[ManagedSession]:
    with _lock:
        seen = set()
        out: List[ManagedSession] = []
        for s in list(_by_entry.values()):
            if id(s) in seen:
                continue
            seen.add(id(s))
            if s.state not in (SessionState.CLOSED, SessionState.ABORTED, SessionState.ERROR):
                out.append(s)
        return out


def _cancel_leg(order_id: str, registry: Dict[str, ManagedSession]) -> None:
    if not order_id:
        return
    try:
        dhan.cancel_order(order_id)
    except Exception:
        pass
    with _lock:
        registry.pop(order_id, None)


def _place_sl(session: ManagedSession, qty: int, avg_px: float) -> None:
    if qty <= 0 or avg_px <= 0 or not ARMOR.attach_exchange_sl:
        return
    if session.sl_order_id and session.filled_qty == qty:
        return
    if session.sl_order_id:
        _cancel_leg(session.sl_order_id, _by_sl)
        session.sl_order_id = ""
    stop_px = avg_px * (1.0 - session.stop_pct)
    trigger = round(stop_px + ARMOR.tick_size, 2)
    cid = f"sl{session.client_order_id[-12:]}"[:30]
    raw = dhan.place_sl_market(
        security_id=session.security_id,
        quantity=int(qty),
        trigger_price=trigger,
        correlation_id=cid,
    )
    inner = raw.get("raw") if isinstance(raw, dict) else {}
    oid = ""
    if isinstance(inner, dict):
        oid = str(inner.get("orderId") or inner.get("order_id") or "")
    session.sl_order_id = oid
    session.state = SessionState.PROTECT_WORKING
    with _lock:
        if oid:
            _by_sl[oid] = session


def _place_tp(session: ManagedSession, qty: int, avg_px: float) -> None:
    if qty <= 0 or avg_px <= 0 or not ARMOR.attach_exchange_tp:
        return
    if session.tp_order_id and session.filled_qty == qty:
        return
    if session.tp_order_id:
        _cancel_leg(session.tp_order_id, _by_tp)
        session.tp_order_id = ""
    tp_px = round(avg_px * (1.0 + session.tp_pct), 2)
    cid = f"tp{session.client_order_id[-12:]}"[:30]
    raw = dhan.place_tp_limit(
        security_id=session.security_id,
        quantity=int(qty),
        price=tp_px,
        correlation_id=cid,
    )
    inner = raw.get("raw") if isinstance(raw, dict) else {}
    oid = ""
    if isinstance(inner, dict):
        oid = str(inner.get("orderId") or inner.get("order_id") or "")
    session.tp_order_id = oid
    session.state = SessionState.PROTECT_WORKING
    with _lock:
        if oid:
            _by_tp[oid] = session


def sync_protective_legs(session: ManagedSession, qty: int, avg_px: float) -> None:
    """Place/resize exchange SL + TP for filled qty."""
    _place_sl(session, qty, avg_px)
    _place_tp(session, qty, avg_px)


def _close_oco(session: ManagedSession, winner: str) -> None:
    """Cancel the other protective leg after SL or TP fills."""
    session.exit_reason = winner
    if winner == "sl" and session.tp_order_id:
        _cancel_leg(session.tp_order_id, _by_tp)
        session.tp_order_id = ""
    elif winner == "tp" and session.sl_order_id:
        _cancel_leg(session.sl_order_id, _by_sl)
        session.sl_order_id = ""
    session.state = SessionState.CLOSED


def handle_order_update(upd: DhanOrderUpdate) -> Optional[ManagedSession]:
    """Apply Dhan WS/REST update; resize SL/TP on partial fill; OCO on exit."""
    session = lookup(order_id=upd.order_id, correlation_id=upd.correlation_id)
    if not session:
        return None

    role = str(session.meta.get("leg_role") or "entry")

    if session.sl_order_id and upd.order_id == session.sl_order_id:
        if upd.status == DhanOrderStatus.TRADED:
            _close_oco(session, "sl")
        elif upd.status == DhanOrderStatus.REJECTED:
            session.state = SessionState.ERROR
            session.error = "sl_rejected"
        return session

    if session.tp_order_id and upd.order_id == session.tp_order_id:
        if upd.status == DhanOrderStatus.TRADED:
            _close_oco(session, "tp")
        elif upd.status == DhanOrderStatus.REJECTED:
            session.error = "tp_rejected"
        return session

    if upd.order_id != session.entry_order_id and upd.correlation_id != session.correlation_id:
        return session

    session.filled_qty = int(upd.traded_qty)
    session.pending_entry_qty = max(0, int(session.requested_qty) - session.filled_qty)
    if upd.avg_traded_price > 0:
        session.avg_entry_px = float(upd.avg_traded_price)

    if upd.status == DhanOrderStatus.REJECTED:
        session.state = SessionState.ERROR
        session.error = "entry_rejected" if role == "entry" else "exit_rejected"
        return session

    if upd.status in (DhanOrderStatus.CANCELLED, DhanOrderStatus.EXPIRED):
        if role == "exit":
            session.state = SessionState.CLOSED if session.filled_qty > 0 else SessionState.ABORTED
            return session
        if session.filled_qty > 0:
            sync_protective_legs(session, session.filled_qty, session.avg_entry_px)
            session.state = SessionState.IN_POSITION
        else:
            session.state = SessionState.ABORTED
        return session

    if upd.status == DhanOrderStatus.PART_TRADED:
        session.state = SessionState.ENTRY_PARTIAL
        if role == "entry":
            sync_protective_legs(session, session.filled_qty, session.avg_entry_px)
        return session

    if upd.status == DhanOrderStatus.TRADED:
        session.filled_qty = int(upd.traded_qty or session.requested_qty)
        session.pending_entry_qty = 0
        if role == "exit":
            session.state = SessionState.CLOSED
            session.exit_reason = "exit_filled"
            return session
        session.state = SessionState.ENTRY_FILLED
        sync_protective_legs(session, session.filled_qty, session.avg_entry_px)
        session.state = SessionState.IN_POSITION
        return session

    return session
