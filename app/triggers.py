"""Active interrupt for the UI. Never places an order.

Two roles share GET /triggers/active and WS signal.trigger:
- approval: manual — user must confirm (placeable true)
- fill_notice: auto/engine already filled — info only (placeable false)
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Set

from app.runners.state import _now

_lock = threading.RLock()
_acked: Set[str] = set()
_fills: List[Dict[str, Any]] = []


def ack(trigger_id: str, action: str = "dismiss") -> Dict[str, Any]:
    tid = str(trigger_id or "").strip()
    with _lock:
        if tid:
            _acked.add(tid)
            global _fills
            _fills = [f for f in _fills if str(f.get("trigger_id")) != tid]
    return {
        "accepted": True,
        "code": "OK",
        "message": None,
        "trigger_id": tid or None,
        "action": action,
    }


def is_acked(trigger_id: str) -> bool:
    with _lock:
        return str(trigger_id) in _acked


def acked_ids() -> Set[str]:
    with _lock:
        return set(_acked)


def _base_trigger(
    *,
    trigger_id: str,
    kind: str,
    role: str,
    underlying: str,
    expiry: Any,
    strike: Any,
    option_type: Any,
    sleeve: str,
    suggested_lots: Any,
    ltp: Any,
    tradingsymbol: str,
    note: str,
    placeable: bool,
    created_at: Any,
    meta: Any,
    filled_qty: Any = None,
    filled_price: Any = None,
    side: Any = None,
) -> Dict[str, Any]:
    kind_l = "sell" if str(kind or "").lower() == "sell" else "buy"
    side_u = str(side or ("SELL" if kind_l == "sell" else "BUY")).upper()
    return {
        "trigger_id": str(trigger_id),
        "kind": kind_l,
        "role": role,
        "underlying": underlying,
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type,
        "sleeve": str(sleeve or "fade").lower(),
        "suggested_lots": suggested_lots,
        "ltp": ltp,
        "tradingsymbol": tradingsymbol or "",
        "note": note,
        "placeable": bool(placeable),
        "created_at": created_at,
        "meta": meta,
        "filled_qty": filled_qty,
        "filled_price": filled_price,
        "side": side_u,
    }


def push_fill_notice(
    *,
    trigger_id: str,
    kind: str,
    underlying: str,
    expiry: Any = None,
    strike: Any = None,
    option_type: Any = None,
    sleeve: str = "fade",
    lots: Any = None,
    filled_qty: Any = None,
    filled_price: Any = None,
    tradingsymbol: str = "",
    note: Optional[str] = None,
    side: Optional[str] = None,
) -> Dict[str, Any]:
    """Newest auto fill — FYI only. Replaces any prior unacked fill_notice."""
    kind_l = "sell" if str(kind or "").lower() == "sell" else "buy"
    side_u = str(side or ("SELL" if kind_l == "sell" else "BUY")).upper()
    verb = "sold" if kind_l == "sell" else "bought"
    px = filled_price
    qty = filled_qty
    lots_i = lots
    if note is None:
        bits = [f"Desk {verb}"]
        if lots_i:
            bits.append(f"{lots_i} lots")
        if underlying:
            bits.append(str(underlying))
        if strike is not None and option_type:
            bits.append(f"{strike} {option_type}")
        if px is not None:
            bits.append(f"at {px}")
        bits.append("No approval needed.")
        note = " ".join(bits)
    trig = _base_trigger(
        trigger_id=str(trigger_id),
        kind=kind_l,
        role="fill_notice",
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        sleeve=sleeve,
        suggested_lots=lots_i,
        ltp=px,
        tradingsymbol=tradingsymbol,
        note=note,
        placeable=False,
        created_at=_now(),
        meta="Informational — already filled.",
        filled_qty=qty,
        filled_price=px,
        side=side_u,
    )
    with _lock:
        global _fills
        tid = str(trigger_id)
        _acked.discard(tid)
        _fills = [f for f in _fills if str(f.get("trigger_id")) != tid]
        _fills.append(trig)
        if len(_fills) > 40:
            _fills = _fills[-40:]
    return {"active": True, "trigger": dict(trig)}


def newest_fill(acked: Optional[Set[str]] = None) -> Dict[str, Any]:
    """Oldest unacked fill so buy then sell both reach the UI."""
    with _lock:
        hidden = set(acked or ()) | _acked
        for row in _fills:
            tid = str(row.get("trigger_id") or "")
            if tid and tid not in hidden:
                return {"active": True, "trigger": dict(row)}
        return {"active": False, "trigger": None}


def newest_pending(
    signals: list,
    *,
    trading_active: bool,
    kill_switch_active: bool,
    halted_underlyings: list,
) -> Dict[str, Any]:
    """At most one interrupt — newest PENDING that has not been dismissed."""
    pending = []
    for s in signals:
        if str(s.get("status") or "").upper() != "PENDING":
            continue
        tid = str(s.get("signal_id") or "")
        if not tid or is_acked(tid):
            continue
        pending.append(s)
    if not pending:
        return {"active": False, "trigger": None}

    row = pending[-1]
    und = str(row.get("underlying") or "")
    halted = und in (halted_underlyings or [])
    placeable = bool(trading_active) and not kill_switch_active and not halted
    kind = "sell" if str(row.get("action") or "BUY").upper() == "SELL" else "buy"
    trigger = _base_trigger(
        trigger_id=str(row.get("signal_id")),
        kind=kind,
        role="approval",
        underlying=und,
        expiry=row.get("expiry"),
        strike=row.get("target_strike"),
        option_type=row.get("option_type"),
        sleeve=str(row.get("sleeve") or "fade").lower(),
        suggested_lots=int(row.get("target_lots") or 0) or None,
        ltp=row.get("ltp"),
        tradingsymbol=row.get("symbol") or "",
        note="Nothing is placed until you confirm.",
        placeable=placeable,
        created_at=row.get("created_at"),
        meta=None if placeable else "Trading halted — cannot place.",
        filled_qty=None,
        filled_price=None,
        side="SELL" if kind == "sell" else "BUY",
    )
    return {"active": True, "trigger": trigger}
