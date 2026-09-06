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


def _pos_key(security_id: str, pack_id: str = "") -> str:
    sid = str(security_id or "").strip()
    pid = str(pack_id or "").strip()
    return f"{pid}::{sid}" if pid else sid


def _find_key(data: Dict[str, Any], security_id: str, pack_id: str = "") -> Optional[str]:
    sid = str(security_id or "").strip()
    if not sid:
        return None
    key = _pos_key(sid, pack_id)
    if key in data["positions"]:
        return key
    if sid in data["positions"] and not pack_id:
        return sid
    if pack_id:
        return None
    for k, pos in data["positions"].items():
        if str(pos.get("security_id") or "") == sid:
            return k
    return None


def keys_for_security_id(security_id: str) -> List[str]:
    sid = str(security_id or "").strip()
    out: List[str] = []
    with _LOCK:
        data = _load()
        for k, pos in data["positions"].items():
            if k == sid or str(pos.get("security_id") or "") == sid:
                out.append(k)
    return out


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
    stop_pct: float = 0.0,
    tp_pct: float = 0.0,
    trail_pct: float = 0.0,
    trail_activate_pct: float = 0.0,
    pack_id: str = "",
) -> Dict[str, Any]:
    """Immediate market fill into the paper book."""
    with _LOCK:
        data = _load()
        sid = str(security_id)
        pid = str(pack_id or "").strip()
        key = _pos_key(sid, pid)
        pos = data["positions"].get(key)
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
                "stop_pct": float(stop_pct or 0.0),
                "tp_pct": float(tp_pct or 0.0),
                "trail_pct": float(trail_pct or 0.0),
                "trail_activate_pct": float(trail_activate_pct or 0.0),
                "peak_px": float(price),
                "current_stop_px": 0.0,
                "pack_id": pid,
                "ledger_key": key,
            }
            data["positions"][key] = pos
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
        if stop_pct:
            pos["stop_pct"] = float(stop_pct)
        if tp_pct:
            pos["tp_pct"] = float(tp_pct)
        if trail_pct:
            pos["trail_pct"] = float(trail_pct)
            pos["trail_activate_pct"] = float(trail_activate_pct or 0.0)
        pos["peak_px"] = max(float(pos.get("peak_px") or 0.0), float(price))
        if pid:
            pos["pack_id"] = pid
            pos["ledger_key"] = key
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
    pack_id: str = "",
) -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        key = _find_key(data, security_id, pack_id)
        if not key:
            return {"ok": False, "reason": "no_position"}
        pos = data["positions"].get(key)
        if not pos or int(pos.get("qty") or 0) <= 0:
            return {"ok": False, "reason": "no_position"}
        return _sell_locked(data, pos, key, qty, price, client_order_id, reason)


def _sell_locked(
    data: Dict[str, Any],
    pos: Dict[str, Any],
    key: str,
    qty: int,
    price: float,
    client_order_id: str,
    reason: str,
) -> Dict[str, Any]:
    sell_qty = min(int(qty), int(pos["qty"]))
    avg = float(pos.get("average_price") or 0)
    sleeve = str(pos.get("sleeve") or "fade")
    underlying = str(pos.get("underlying") or "")
    security_id = str(pos.get("security_id") or key)
    pack_id = str(pos.get("pack_id") or "")
    pnl = round((float(price) - avg) * sell_qty, 2)
    broker_oid = f"paper_{uuid4().hex[:12]}"
    left = int(pos["qty"]) - sell_qty
    order = {
        "order_id": broker_oid,
        "client_order_id": client_order_id,
        "broker_order_id": broker_oid,
        "symbol": pos.get("symbol"),
        "underlying": underlying,
        "security_id": security_id,
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
        "pack_id": pack_id or None,
    }
    data["orders"].append(order)
    if left <= 0:
        data["positions"].pop(key, None)
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
        "security_id": security_id,
        "pack_id": pack_id or None,
        "symbol": pos.get("symbol") if left > 0 else order.get("symbol"),
        "expiry": pos.get("expiry") if left > 0 else None,
        "strike": pos.get("strike") if left > 0 else None,
        "option_type": pos.get("option_type") if left > 0 else None,
        "lots": order.get("lots"),
        "lot_size": order.get("lot_size"),
        "reason": reason,
    }


def peek(security_id: str, pack_id: str = "") -> Optional[Dict[str, Any]]:
    sid = str(security_id or "").strip()
    if not sid:
        return None
    with _LOCK:
        data = _load()
        key = _find_key(data, sid, pack_id)
        if not key:
            return None
        pos = data["positions"].get(key)
        return dict(pos) if pos else None


def ensure_recipe(
    security_id: str,
    *,
    stop_pct: float,
    tp_pct: float,
    trail_pct: float,
    trail_activate_pct: float,
    pack_id: str = "",
) -> None:
    """Fill YAML exits onto a lot that was opened before recipe was stored. Never overwrite."""
    if float(stop_pct or 0) <= 0:
        return
    sid = str(security_id or "").strip()
    with _LOCK:
        data = _load()
        key = _find_key(data, sid, pack_id) or sid
        pos = data["positions"].get(key)
        if not pos or int(pos.get("qty") or 0) <= 0:
            return
        if float(pos.get("stop_pct") or 0.0) > 0:
            return
        pos["stop_pct"] = float(stop_pct)
        pos["tp_pct"] = float(tp_pct or 0.0)
        pos["trail_pct"] = float(trail_pct or 0.0)
        pos["trail_activate_pct"] = float(trail_activate_pct or 0.0)
        _save(data)


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


def find_traded_order(order_id: str) -> Optional[Dict[str, Any]]:
    oid = str(order_id or "").strip()
    if not oid:
        return None
    with _LOCK:
        data = _load()
        for order in data.get("orders") or []:
            if not isinstance(order, dict):
                continue
            if oid in (
                str(order.get("order_id") or ""),
                str(order.get("broker_order_id") or ""),
                str(order.get("client_order_id") or ""),
            ):
                return dict(order)
    return None


def is_paper_order_id(order_id: str) -> bool:
    """Paper fills use paper_* oids. Live client ids are desk-* — only match if already in the ledger."""
    oid = str(order_id or "").strip()
    if not oid:
        return False
    if oid.startswith("paper_"):
        return True
    return find_traded_order(oid) is not None


def _protective_reason(pos: Dict[str, Any], ltp: float) -> Optional[str]:
    from app.execution.trail import effective_stop_px, floor_stop_px

    entry = float(pos.get("average_price") or 0.0)
    stop_pct = float(pos.get("stop_pct") or 0.0)
    tp_pct = float(pos.get("tp_pct") or 0.0)
    trail_pct = float(pos.get("trail_pct") or 0.0)
    act = float(pos.get("trail_activate_pct") or 0.0)
    if entry <= 0 or stop_pct <= 0:
        return None
    peak = max(float(pos.get("peak_px") or 0.0), float(ltp), entry)
    pos["peak_px"] = peak
    stop = effective_stop_px(
        entry_px=entry,
        peak_px=peak,
        stop_pct=stop_pct,
        trail_pct=trail_pct,
        trail_activate_pct=act,
    )
    pos["current_stop_px"] = stop
    if tp_pct > 0 and ltp >= entry * (1.0 + tp_pct) - 1e-9:
        return "take_profit"
    if ltp <= stop + 1e-9:
        floor = floor_stop_px(entry, stop_pct)
        return "trail_stop" if stop > floor + 1e-6 else "stop"
    return None


def mark_and_maybe_exit(security_id: str, ltp: float, pack_id: str = "") -> Optional[Dict[str, Any]]:
    """Apply YAML stop / TP / trail against live LTP. Returns sell payload or None."""
    if ltp <= 0:
        return None
    with _LOCK:
        data = _load()
        key = _find_key(data, str(security_id), pack_id)
        if not key:
            return None
        pos = data["positions"].get(key)
        if not pos or int(pos.get("qty") or 0) <= 0:
            return None
        pos["ltp"] = float(ltp)
        pos["mark_price"] = float(ltp)
        avg = float(pos.get("average_price") or 0.0)
        qty = int(pos.get("qty") or 0)
        pos["unrealized_pnl"] = round((float(ltp) - avg) * qty, 2)
        reason = _protective_reason(pos, float(ltp))
        _save(data)
        if not reason:
            return None
        return _sell_locked(
            data,
            pos,
            key,
            qty,
            float(ltp),
            client_order_id=f"paper-protect-{str(security_id)[:12]}",
            reason=reason,
        )


def desk_positions(book_list: list) -> Dict[str, Any]:
    """Paper ledger + Dhan only for books that already passed live cutover."""
    from app.books.live_cutover import book_uses_dhan
    from app.brokers.dhan import client as dhan

    dhan_unds = {b.name for b in (book_list or []) if book_uses_dhan(b.name, b)}
    dhan_rows: List[dict] = []
    detail = None
    if dhan_unds:
        try:
            grid = dhan.positions_grid()
            dhan_rows = list(grid.get("rows") or [])
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)[:240]
    paper_rows = list((positions_grid().get("rows") or []))
    rows = merge_position_rows(dhan_rows, paper_rows, dhan_underlyings=dhan_unds)
    return {
        "rows": rows,
        "row_count": len(rows),
        "snapshot_at": _now(),
        "detail": detail or "paper_ledger",
    }
