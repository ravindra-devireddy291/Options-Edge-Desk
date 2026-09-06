"""Sync entry/exit placement with spread gate + limit chase (REST/WS depth)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from app.brokers.dhan import client as dhan
from app.execution.config import ARMOR
from app.execution.dhan_ws_feed import get_depth
from app.execution.freshness import tick_ok
from app.execution.spread_chaser import next_limit_price
from app.execution.sessions import bind_entry_order_id, register
from app.execution.types import DepthSnapshot, ManagedSession


def _depth_from_rest(security_id: str, quote: Dict[str, Any]) -> DepthSnapshot:
    ltp = float(quote.get("ltp") or 0)
    bid = float(quote.get("bid") if quote.get("bid") is not None else ltp)
    ask = float(quote.get("ask") if quote.get("ask") is not None else ltp)
    quoted_at = quote.get("quoted_at")
    if isinstance(quoted_at, str):
        try:
            ts = datetime.fromisoformat(quoted_at.replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(timezone.utc)
    else:
        ts = datetime.now(timezone.utc)
    return DepthSnapshot(
        security_id=str(security_id),
        symbol="",
        bid=bid,
        ask=ask,
        ltp=ltp,
        ts=ts,
    )


def _resolve_depth(security_id: str) -> Tuple[Optional[DepthSnapshot], str, bool]:
    """Return depth, refuse_reason, from_ws."""
    ws = get_depth(security_id)
    if ws and tick_ok(ws.ts, max_age_ms=ARMOR.max_tick_age_ms_ws):
        return ws, "", True
    try:
        q = dhan.market_quote_option(str(security_id))
    except Exception as exc:  # noqa: BLE001
        return None, f"quote_failed:{exc}", False
    depth = _depth_from_rest(security_id, q)
    if not tick_ok(depth.ts, max_age_ms=ARMOR.max_tick_age_ms_rest):
        return None, "stale_rest_quote", False
    return depth, "", False


def resolve_depth(security_id: str) -> Tuple[Optional[DepthSnapshot], str, bool]:
    return _resolve_depth(security_id)


def place_armed_entry(
    *,
    underlying: str,
    sleeve: str,
    security_id: str,
    symbol: str,
    quantity: int,
    side: str,
    stop_pct: float,
    tp_pct: float,
    trail_pct: float = 0.0,
    trail_activate_pct: float = 0.0,
    correlation_id: str,
    client_order_id: str,
    ref_px: Optional[float] = None,
    tag: str = "edge-desk-armor",
) -> Dict[str, Any]:
    """Spread-checked limit entry; registers session for WS SL on fill."""
    if not ARMOR.enabled or side.upper() != "BUY":
        return dhan.place_order(
            security_id=security_id,
            transaction_type=side,
            quantity=quantity,
            order_type="MARKET",
            correlation_id=correlation_id,
            tag=tag,
        )

    depth, refuse, _from_ws = _resolve_depth(security_id)
    if depth is None:
        return {
            "accepted": False,
            "code": "SPREAD_REFUSE" if "spread" in refuse else "STALE_TICK",
            "message": refuse or "no_depth",
            "correlation_id": correlation_id,
        }

    chase = next_limit_price(depth, ARMOR, ref_px=ref_px)
    if chase.refused:
        return {
            "accepted": False,
            "code": "SPREAD_REFUSE",
            "message": chase.reason,
            "spread_pct": chase.spread_pct,
            "correlation_id": correlation_id,
        }

    order_type = "LIMIT" if ARMOR.use_limit_entry else "MARKET"
    price = chase.limit_px if order_type == "LIMIT" else 0.0
    raw = dhan.place_order(
        security_id=security_id,
        transaction_type=side,
        quantity=quantity,
        order_type=order_type,
        price=price,
        correlation_id=correlation_id,
        tag=tag,
    )

    inner = raw.get("raw") if isinstance(raw, dict) else {}
    broker_id = ""
    if isinstance(inner, dict):
        broker_id = str(inner.get("orderId") or inner.get("order_id") or "")

    session = ManagedSession(
        client_order_id=client_order_id or f"desk-{uuid4().hex[:12]}",
        correlation_id=correlation_id,
        underlying=underlying,
        sleeve=sleeve,
        security_id=str(security_id),
        symbol=symbol,
        requested_qty=int(quantity),
        stop_pct=float(stop_pct),
        tp_pct=float(tp_pct),
        trail_pct=float(trail_pct),
        trail_activate_pct=float(trail_activate_pct),
        limit_px=chase.limit_px,
        pending_entry_qty=int(quantity),
        meta={
            "spread_pct": chase.spread_pct,
            "from_ws": _from_ws,
            "leg_role": "entry",
            "chase_deadline_ts": time.time() + float(ARMOR.chase_timeout_s),
        },
    )
    if broker_id:
        bind_entry_order_id(session, broker_id)
    register(session)

    return {
        **raw,
        "armor": {
            "limit_px": chase.limit_px,
            "spread_pct": chase.spread_pct,
            "order_type": order_type,
            "session_registered": bool(broker_id),
        },
    }


def place_armed_exit(
    *,
    underlying: str,
    sleeve: str,
    security_id: str,
    symbol: str,
    quantity: int,
    correlation_id: str,
    client_order_id: str,
    ref_px: Optional[float] = None,
    tag: str = "edge-desk-exit",
) -> Dict[str, Any]:
    """Spread-checked limit exit; chases until fill or timeout."""
    if not ARMOR.enabled:
        return dhan.place_order(
            security_id=security_id,
            transaction_type="SELL",
            quantity=quantity,
            order_type="MARKET",
            correlation_id=correlation_id,
            tag=tag,
        )

    depth, refuse, _from_ws = _resolve_depth(security_id)
    if depth is None:
        return {
            "accepted": False,
            "code": "SPREAD_REFUSE" if "spread" in refuse else "STALE_TICK",
            "message": refuse or "no_depth",
            "correlation_id": correlation_id,
        }

    chase = next_limit_price(depth, ARMOR, ref_px=ref_px, side="sell")
    if chase.refused:
        return {
            "accepted": False,
            "code": "SPREAD_REFUSE",
            "message": chase.reason,
            "spread_pct": chase.spread_pct,
            "correlation_id": correlation_id,
        }

    order_type = "LIMIT" if ARMOR.use_limit_exit else "MARKET"
    price = chase.limit_px if order_type == "LIMIT" else 0.0
    raw = dhan.place_order(
        security_id=security_id,
        transaction_type="SELL",
        quantity=quantity,
        order_type=order_type,
        price=price,
        correlation_id=correlation_id,
        tag=tag,
    )

    inner = raw.get("raw") if isinstance(raw, dict) else {}
    broker_id = ""
    if isinstance(inner, dict):
        broker_id = str(inner.get("orderId") or inner.get("order_id") or "")

    session = ManagedSession(
        client_order_id=client_order_id or f"desk-{uuid4().hex[:12]}",
        correlation_id=correlation_id,
        underlying=underlying,
        sleeve=sleeve,
        security_id=str(security_id),
        symbol=symbol,
        requested_qty=int(quantity),
        stop_pct=0.0,
        tp_pct=0.0,
        limit_px=chase.limit_px,
        pending_entry_qty=int(quantity),
        meta={
            "spread_pct": chase.spread_pct,
            "from_ws": _from_ws,
            "leg_role": "exit",
            "chase_deadline_ts": time.time() + float(ARMOR.chase_timeout_s),
        },
    )
    if broker_id:
        bind_entry_order_id(session, broker_id)
    register(session)

    return {
        **raw,
        "armor": {
            "limit_px": chase.limit_px,
            "spread_pct": chase.spread_pct,
            "order_type": order_type,
            "session_registered": bool(broker_id),
            "leg_role": "exit",
        },
    }
