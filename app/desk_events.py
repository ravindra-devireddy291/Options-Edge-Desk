"""Emit book deltas matching UI DESK_SNAPSHOT_WS / desk-delta.ts shapes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.ws_hub import HUB


def position_key(row: Dict[str, Any]) -> str:
    sid = row.get("security_id")
    if sid is not None and str(sid).strip():
        return str(sid)
    und = str(row.get("underlying") or "")
    strike = row.get("strike")
    opt = str(row.get("option_type") or "")
    expiry = str(row.get("expiry") or "")
    return f"{und}|{strike}|{opt}|{expiry}"


def emit_position_upsert(row: Dict[str, Any]) -> None:
    if not row:
        return
    HUB.broadcast("position.upsert", dict(row))


def emit_position_remove(row_or_key: Any) -> None:
    if isinstance(row_or_key, dict):
        key = position_key(row_or_key)
    else:
        key = str(row_or_key or "")
    if not key:
        return
    HUB.broadcast("position.remove", {"key": key})


def emit_order_upsert(order: Dict[str, Any]) -> None:
    if not order:
        return
    HUB.broadcast("order.upsert", dict(order))


def emit_order_remove(order_id: str) -> None:
    oid = str(order_id or "")
    if not oid:
        return
    HUB.broadcast("order.remove", {"order_id": oid})


def emit_trade_append(trade: Dict[str, Any]) -> None:
    if not trade:
        return
    HUB.broadcast("trade.append", dict(trade))


def emit_mock_buy(pos: Dict[str, Any], order: Optional[Dict[str, Any]], trade: Optional[Dict[str, Any]]) -> None:
    """Mock fills are immediate TRADED — skip working order.upsert."""
    if order and str(order.get("status") or "").upper() in ("TRANSIT", "PENDING"):
        emit_order_upsert(order)
    elif order:
        oid = str(order.get("order_id") or order.get("client_order_id") or "")
        if oid:
            emit_order_remove(oid)
    if pos and int(pos.get("qty") or 0) != 0:
        emit_position_upsert(pos)
    if trade:
        emit_trade_append(trade)


def emit_mock_sell(
    pos: Optional[Dict[str, Any]],
    order: Optional[Dict[str, Any]],
    trade: Optional[Dict[str, Any]],
    *,
    removed_key: Optional[str] = None,
) -> None:
    if order:
        oid = str(order.get("order_id") or order.get("client_order_id") or "")
        if oid:
            emit_order_remove(oid)
    if pos is not None and int(pos.get("qty") or 0) != 0:
        emit_position_upsert(pos)
    elif removed_key:
        emit_position_remove(removed_key)
    elif pos is not None:
        emit_position_remove(pos)
    if trade:
        emit_trade_append(trade)


def emit_paper_place_result(result: Dict[str, Any], *, positions_row: Optional[Dict[str, Any]] = None) -> None:
    if not result.get("accepted"):
        return
    order = result.get("order")
    if isinstance(order, dict):
        st = str(order.get("status") or "").upper()
        if st in ("TRANSIT", "PENDING"):
            emit_order_upsert(order)
        elif st in ("TRADED", "FILLED", "CANCELLED", "REJECTED"):
            oid = str(order.get("order_id") or order.get("broker_order_id") or order.get("client_order_id") or "")
            if oid:
                emit_order_remove(oid)
    if positions_row:
        if int(positions_row.get("qty") or positions_row.get("quantity") or 0) != 0:
            emit_position_upsert(positions_row)
        else:
            emit_position_remove(positions_row)
