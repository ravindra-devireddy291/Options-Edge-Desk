"""Desk paper OMS — same fill shape as live, no Dhan place (virtual money)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.session import session_day, to_utc_z
from datetime import datetime, timezone

_LOCK = threading.RLock()
_ROOT = Path(__file__).resolve().parents[1] / "data" / "paper_ledger"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _path() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT / "state.json"


def _load() -> Dict[str, Any]:
    path = _path()
    if not path.exists():
        return {"day": session_day().isoformat(), "positions": {}, "orders": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"day": session_day().isoformat(), "positions": {}, "orders": []}
    day = session_day().isoformat()
    if str(data.get("day") or "") != day:
        # New IST day — keep closed history in journals; reset open book.
        return {"day": day, "positions": {}, "orders": []}
    data.setdefault("positions", {})
    data.setdefault("orders", [])
    return data


def _save(data: Dict[str, Any]) -> None:
    path = _path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def reset_for_tests() -> None:
    with _LOCK:
        path = _path()
        if path.exists():
            path.unlink()


def apply_buy(
    *,
    underlying: str,
    sleeve: str,
    security_id: str,
    symbol: str,
    qty: int,
    lots: int,
    lot_size: int,
    price: float,
    client_order_id: str,
    expiry: Any = None,
    strike: Any = None,
    option_type: Any = None,
) -> Dict[str, Any]:
    """Immediate market fill into the paper book."""
    with _LOCK:
        data = _load()
        sid = str(security_id)
        pos = data["positions"].get(sid)
        broker_oid = f"paper_{uuid4().hex[:12]}"
        if pos is None:
            pos = {
                "symbol": symbol,
                "tradingsymbol": symbol,
                "underlying": underlying,
                "security_id": sid,
                "expiry": expiry,
                "strike": strike,
                "option_type": option_type,
                "sleeve": sleeve,
                "side": "LONG",
                "qty": 0,
                "lots": 0,
                "lot_size": lot_size,
                "average_price": 0.0,
                "ltp": price,
                "mark_price": price,
                "unrealized_pnl": 0.0,
                "broker_qty": 0,
                "shadow_qty": 0,
                "drift_status": "paper",
                "client_order_id": client_order_id,
                "broker_order_id": broker_oid,
            }
            data["positions"][sid] = pos
        old_qty = int(pos["qty"])
        old_avg = float(pos.get("average_price") or 0)
        new_qty = old_qty + int(qty)
        if new_qty > 0:
            pos["average_price"] = round((old_avg * old_qty + float(price) * int(qty)) / new_qty, 4)
        pos["qty"] = new_qty
        pos["quantity"] = new_qty
        pos["lots"] = max(1, new_qty // max(1, int(lot_size))) if new_qty else 0
        pos["lot_size"] = lot_size
        pos["ltp"] = float(price)
        pos["mark_price"] = float(price)
        pos["unrealized_pnl"] = 0.0
        pos["side"] = "LONG" if new_qty > 0 else "SHORT"
        pos["broker_qty"] = new_qty
        order = {
            "order_id": broker_oid,
            "client_order_id": client_order_id,
            "broker_order_id": broker_oid,
            "symbol": symbol,
            "underlying": underlying,
            "security_id": sid,
            "side": "BUY",
            "qty": int(qty),
            "lots": lots,
            "lot_size": lot_size,
            "price": float(price),
            "filled_qty": int(qty),
            "status": "TRADED",
            "order_type": "MARKET",
            "placed_at": _now(),
            "cancellable": False,
            "origin": "paper",
        }
        data["orders"].append(order)
        _save(data)
        return {"position": dict(pos), "order": order, "broker_order_id": broker_oid}


def apply_sell(
    *,
    security_id: str,
    qty: int,
    price: float,
    client_order_id: str,
    reason: str = "exit",
) -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        sid = str(security_id)
        pos = data["positions"].get(sid)
        if not pos or int(pos.get("qty") or 0) <= 0:
            return {"ok": False, "reason": "no_position"}
        sell_qty = min(int(qty), int(pos["qty"]))
        avg = float(pos.get("average_price") or 0)
        sleeve = str(pos.get("sleeve") or "fade")
        underlying = str(pos.get("underlying") or "")
        pnl = round((float(price) - avg) * sell_qty, 2)
        broker_oid = f"paper_{uuid4().hex[:12]}"
        left = int(pos["qty"]) - sell_qty
        order = {
            "order_id": broker_oid,
            "client_order_id": client_order_id,
            "broker_order_id": broker_oid,
            "symbol": pos.get("symbol"),
            "underlying": underlying,
            "security_id": sid,
            "side": "SELL",
            "qty": sell_qty,
            "lots": pos.get("lots"),
            "lot_size": pos.get("lot_size"),
            "price": float(price),
            "filled_qty": sell_qty,
            "status": "TRADED",
            "order_type": "MARKET",
            "placed_at": _now(),
            "cancellable": False,
            "origin": "paper",
            "exit_reason": reason,
            "realized_pnl": pnl,
            "sleeve": sleeve,
        }
        data["orders"].append(order)
        if left <= 0:
            data["positions"].pop(sid, None)
        else:
            pos["qty"] = left
            pos["quantity"] = left
            lot_size = max(1, int(pos.get("lot_size") or 1))
            pos["lots"] = max(1, left // lot_size)
            pos["ltp"] = float(price)
            pos["mark_price"] = float(price)
            pos["unrealized_pnl"] = round((float(price) - avg) * left, 2)
        _save(data)
        return {
            "ok": True,
            "broker_order_id": broker_oid,
            "order": order,
            "sold_qty": sell_qty,
            "entry_avg": avg,
            "exit_price": float(price),
            "realized_pnl": pnl,
            "sleeve": sleeve,
            "underlying": underlying,
            "closed": left <= 0,
        }


def positions_grid() -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        rows: List[dict] = []
        for pos in data["positions"].values():
            if int(pos.get("qty") or 0) == 0:
                continue
            row = dict(pos)
            # Refresh mark from Dhan feed when possible.
            try:
                from app.execution.dhan_ws_feed import get_depth

                depth = get_depth(str(pos.get("security_id") or ""))
                if depth is not None and depth.ltp is not None:
                    ltp = float(depth.ltp)
                    avg = float(pos.get("average_price") or 0)
                    qty = int(pos.get("qty") or 0)
                    row["ltp"] = ltp
                    row["mark_price"] = ltp
                    row["unrealized_pnl"] = round((ltp - avg) * qty, 2)
            except Exception:
                pass
            rows.append(row)
        return {
            "rows": rows,
            "row_count": len(rows),
            "snapshot_at": _now(),
            "detail": "paper_ledger",
        }


def open_orders() -> Dict[str, Any]:
    """Paper fills immediately — no working orders."""
    return {"orders": [], "count": 0, "snapshot_at": _now(), "detail": "paper_ledger"}


def merge_position_rows(dhan_rows: List[dict], paper_rows: List[dict], *, dhan_underlyings: set) -> List[dict]:
    """Live books from Dhan; paper books from ledger."""
    out: List[dict] = []
    for row in dhan_rows:
        und = str(row.get("underlying") or "").upper()
        if und in dhan_underlyings:
            out.append(row)
    for row in paper_rows:
        und = str(row.get("underlying") or "").upper()
        if und not in dhan_underlyings:
            out.append(row)
    return out
