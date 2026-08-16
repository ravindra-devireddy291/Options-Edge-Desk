"""In-memory two-book mock ledger (positions, orders, fills, signals).

REST handlers and the background clock must hold `self.lock` (asyncio.Lock)
before any read or write of positions, orders, or today_net.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.runners.state import _now
from app.session import to_utc_z


def mock_broker_order_id() -> str:
    """OMS-contract broker id when Dhan is bypassed."""
    return f"mock_broker_{uuid4().hex}"


class MockLedger:
    def __init__(self) -> None:
        self.lock: Optional[asyncio.Lock] = None
        self.day: str = ""
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.orders: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []
        self.signals: List[Dict[str, Any]] = []
        self.capital = {"NIFTY": 100_000.0, "BANKNIFTY": 200_000.0}
        self.realized = {"NIFTY": 0.0, "BANKNIFTY": 0.0}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Create asyncio.Lock on the FastAPI event loop."""
        self.lock = asyncio.Lock()

    def reset(self, day: str, events: List[Dict[str, Any]]) -> None:
        self.day = day
        self.positions = {}
        self.orders = []
        self.trades = []
        self.realized = {"NIFTY": 0.0, "BANKNIFTY": 0.0}
        self.signals = []
        for ev in events:
            self.signals.append(
                {
                    "signal_id": ev["signal_id"],
                    "time": ev["entry_at"].strftime("%H:%M:%S"),
                    "underlying": ev["underlying"],
                    "sleeve": ev["sleeve"],
                    "action": "BUY",
                    "option_type": ev["option_type"],
                    "target_strike": ev["strike"],
                    "target_lots": ev["lots"],
                    "gap_pts": ev.get("gap_pts"),
                    "status": "PENDING",
                    "notes": "ok",
                    "symbol": ev["symbol"],
                    "expiry": ev["expiry"],
                    "ltp": ev["entry"],
                    "created_at": to_utc_z(ev["entry_at"]),
                    "event_id": ev["signal_id"],
                }
            )

    def _key(self, und: str, symbol: str) -> str:
        return f"{und}:{symbol}"

    def set_signal(self, signal_id: str, status: str, notes: str = "") -> None:
        for s in self.signals:
            if s["signal_id"] == signal_id:
                s["status"] = status
                if notes:
                    s["notes"] = notes

    def signal_status(self, signal_id: str) -> Optional[str]:
        for s in self.signals:
            if s["signal_id"] == signal_id:
                return s["status"]
        return None

    def _sync_qty(self, pos: Dict[str, Any]) -> None:
        lot_size = max(1, int(pos.get("lot_size") or 1))
        tape_q = max(0, int(pos.get("tape_qty") or 0))
        overlay_q = max(0, int(pos.get("overlay_qty") or 0))
        pos["tape_qty"] = tape_q
        pos["overlay_qty"] = overlay_q
        pos["tape_lots"] = tape_q // lot_size
        pos["overlay_lots"] = overlay_q // lot_size
        new_qty = tape_q + overlay_q
        pos["qty"] = new_qty
        pos["quantity"] = new_qty
        pos["lots"] = abs(new_qty) // lot_size
        pos["side"] = "LONG" if new_qty >= 0 else "SHORT"

    def open_buy(
        self,
        *,
        ev: Optional[Dict[str, Any]] = None,
        underlying: str,
        symbol: str,
        security_id: str,
        expiry: str,
        strike: float,
        option_type: str,
        sleeve: str,
        lots: int,
        lot_size: int,
        price: float,
        qty: Optional[int] = None,
        client_order_id: Optional[str] = None,
        origin: str = "overlay",
        tape_signal_id: Optional[str] = None,
        tape_exit_reason: Optional[str] = None,
        tape_exit_px: Optional[float] = None,
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        q = int(qty if qty is not None else lots * lot_size)
        oid = client_order_id or f"paper-{uuid4().hex[:12]}"
        broker_oid = mock_broker_order_id()
        origin = "tape" if origin == "tape" else "overlay"
        key = self._key(underlying, symbol)
        pos = self.positions.get(key)
        if pos is None:
            pos = {
                "symbol": symbol,
                "tradingsymbol": symbol,
                "underlying": underlying,
                "security_id": security_id,
                "expiry": expiry,
                "strike": strike,
                "option_type": option_type,
                "sleeve": sleeve,
                "side": "LONG",
                "qty": 0,
                "quantity": 0,
                "lots": 0,
                "lot_size": lot_size,
                "average_price": 0.0,
                "mark_price": price,
                "ltp": price,
                "unrealized_pnl": 0.0,
                "tape_qty": 0,
                "overlay_qty": 0,
                "tape_lots": 0,
                "overlay_lots": 0,
                "tape_signal_id": None,
                "tape_exit_reason": None,
                "tape_exit_px": None,
                "event_id": None,
                "trade_id": oid,
            }
            self.positions[key] = pos
        old_qty = int(pos["qty"])
        old_avg = float(pos["average_price"] or 0)
        new_qty = old_qty + q
        if new_qty > 0:
            pos["average_price"] = round((old_avg * old_qty + price * q) / new_qty, 4)
        if origin == "tape":
            pos["tape_qty"] = int(pos.get("tape_qty") or 0) + q
            if tape_signal_id:
                pos["tape_signal_id"] = tape_signal_id
                pos["tape_exit_reason"] = tape_exit_reason
                pos["tape_exit_px"] = tape_exit_px
                pos["event_id"] = event_id
        else:
            pos["overlay_qty"] = int(pos.get("overlay_qty") or 0) + q
        self._sync_qty(pos)
        pos["ltp"] = price
        pos["mark_price"] = price
        self.orders.append(
            {
                "order_id": oid,
                "client_order_id": oid,
                "broker_order_id": broker_oid,
                "symbol": symbol,
                "underlying": underlying,
                "expiry": expiry,
                "strike": strike,
                "option_type": option_type,
                "side": "BUY",
                "qty": q,
                "lots": lots,
                "lot_size": lot_size,
                "price": price,
                "average_price": price,
                "filled_qty": q,
                "filled_quantity": q,
                "status": "TRADED",
                "order_type": "MARKET",
                "origin": origin,
                "placed_at": _now(),
                "cancellable": False,
            }
        )
        existing = next((t for t in self.trades if t.get("trade_id") == pos["trade_id"] and t.get("exit_reason") == "open"), None)
        if existing is None:
            self.trades.append(
                {
                    "trade_id": pos["trade_id"],
                    "underlying": underlying,
                    "sleeve": sleeve,
                    "symbol": symbol,
                    "side": "BUY",
                    "qty": pos["qty"],
                    "lots": pos["lots"],
                    "lot_size": lot_size,
                    "entry_price": pos["average_price"],
                    "exit_price": None,
                    "exit_reason": "open",
                    "realized_pnl": None,
                    "costs": 0,
                    "net_pnl": None,
                    "lab_entry": (ev or {}).get("entry"),
                    "broker_entry": pos["average_price"],
                    "lab_exit": None,
                    "broker_exit": None,
                    "slip_entry": 0,
                    "slip_exit": None,
                    "closed_at": None,
                    "tape_qty": pos["tape_qty"],
                    "overlay_qty": pos["overlay_qty"],
                }
            )
        else:
            existing["qty"] = pos["qty"]
            existing["lots"] = pos["lots"]
            existing["entry_price"] = pos["average_price"]
            existing["broker_entry"] = pos["average_price"]
            existing["tape_qty"] = pos["tape_qty"]
            existing["overlay_qty"] = pos["overlay_qty"]
        return {
            "client_order_id": oid,
            "broker_order_id": broker_oid,
            "quantity": q,
            "lots": lots,
            "lot_size": lot_size,
            "price": price,
            "status": "TRADED",
            "origin": origin,
        }

    def sell(
        self,
        *,
        underlying: str,
        symbol: str,
        lots: int,
        lot_size: int,
        price: float,
        client_order_id: Optional[str] = None,
        reason: str = "exit",
        lab_exit: Optional[float] = None,
        qty: Optional[int] = None,
        close_source: str = "user",
    ) -> Dict[str, Any]:
        oid = client_order_id or f"paper-{uuid4().hex[:12]}"
        broker_oid = mock_broker_order_id()
        requested = int(qty if qty is not None else lots * lot_size)
        key = self._key(underlying, symbol)
        pos = self.positions.get(key)
        if not pos or int(pos["qty"]) <= 0:
            raise RuntimeError("no long position to sell")
        tape_q = int(pos.get("tape_qty") or 0)
        overlay_q = int(pos.get("overlay_qty") or 0)
        if close_source == "tape":
            close_q = min(requested, tape_q)
            pos["tape_qty"] = tape_q - close_q
        elif close_source == "all":
            close_q = min(requested, int(pos["qty"]))
            take_o = min(close_q, overlay_q)
            pos["overlay_qty"] = overlay_q - take_o
            pos["tape_qty"] = tape_q - (close_q - take_o)
        else:
            # User overlay SELL: overlay lots first, then tape if they sell more.
            close_q = min(requested, int(pos["qty"]))
            take_o = min(close_q, overlay_q)
            pos["overlay_qty"] = overlay_q - take_o
            pos["tape_qty"] = tape_q - (close_q - take_o)
        if close_q <= 0:
            raise RuntimeError("no matching quantity to sell")
        avg = float(pos["average_price"])
        pnl = round((price - avg) * close_q, 2)
        self._sync_qty(pos)
        und = underlying
        self.realized[und] = round(self.realized.get(und, 0) + pnl, 2)
        self.orders.append(
            {
                "order_id": oid,
                "client_order_id": oid,
                "broker_order_id": broker_oid,
                "symbol": symbol,
                "underlying": underlying,
                "expiry": pos.get("expiry"),
                "strike": pos.get("strike"),
                "option_type": pos.get("option_type"),
                "side": "SELL",
                "qty": close_q,
                "lots": close_q // max(1, lot_size),
                "lot_size": lot_size,
                "price": price,
                "average_price": price,
                "filled_qty": close_q,
                "filled_quantity": close_q,
                "status": "TRADED",
                "order_type": "MARKET",
                "origin": close_source,
                "placed_at": _now(),
                "cancellable": False,
            }
        )
        open_row = next((t for t in self.trades if t.get("trade_id") == pos.get("trade_id") and t.get("exit_reason") == "open"), None)
        if pos["qty"] <= 0:
            if open_row:
                open_row["exit_price"] = price
                open_row["exit_reason"] = reason
                open_row["realized_pnl"] = pnl
                open_row["net_pnl"] = pnl
                open_row["broker_exit"] = price
                open_row["lab_exit"] = lab_exit
                open_row["slip_exit"] = round(price - float(lab_exit), 4) if lab_exit is not None else 0
                open_row["closed_at"] = _now()
                open_row["qty"] = close_q
                open_row["tape_qty"] = 0
                open_row["overlay_qty"] = 0
            self.positions.pop(key, None)
        else:
            if open_row:
                open_row["qty"] = pos["qty"]
                open_row["lots"] = pos["lots"]
                open_row["tape_qty"] = pos["tape_qty"]
                open_row["overlay_qty"] = pos["overlay_qty"]
            self.trades.append(
                {
                    "trade_id": f"{oid}-partial",
                    "underlying": underlying,
                    "sleeve": pos.get("sleeve") or "fade",
                    "symbol": symbol,
                    "side": "SELL",
                    "qty": close_q,
                    "lots": close_q // max(1, lot_size),
                    "lot_size": lot_size,
                    "entry_price": avg,
                    "exit_price": price,
                    "exit_reason": reason,
                    "realized_pnl": pnl,
                    "costs": 0,
                    "net_pnl": pnl,
                    "lab_entry": avg,
                    "broker_entry": avg,
                    "lab_exit": lab_exit,
                    "broker_exit": price,
                    "slip_entry": 0,
                    "slip_exit": 0,
                    "closed_at": _now(),
                    "origin": close_source,
                }
            )
        return {
            "client_order_id": oid,
            "broker_order_id": broker_oid,
            "quantity": close_q,
            "price": price,
            "status": "TRADED",
            "origin": close_source,
        }

    def mark_all(self, ltp_by_symbol: Dict[str, float]) -> None:
        for pos in self.positions.values():
            ltp = ltp_by_symbol.get(pos["symbol"])
            if ltp is None:
                continue
            pos["ltp"] = ltp
            pos["mark_price"] = ltp
            pos["unrealized_pnl"] = round((ltp - float(pos["average_price"])) * int(pos["qty"]), 2)

    def positions_grid(self) -> Dict[str, Any]:
        rows = [dict(p) for p in self.positions.values() if int(p.get("qty") or 0) != 0]
        return {"rows": rows, "row_count": len(rows), "snapshot_at": _now(), "detail": None}

    def open_orders(self) -> Dict[str, Any]:
        working = [o for o in self.orders if str(o.get("status") or "").upper() in ("TRANSIT", "PENDING")]
        return {"orders": list(working), "count": len(working), "snapshot_at": _now(), "detail": None}

    def enqueue_working(self, order: Dict[str, Any]) -> None:
        self.orders.append(order)

    def complete_working(self, order_id: str, status: str = "TRADED") -> Optional[Dict[str, Any]]:
        for o in self.orders:
            if o.get("order_id") == order_id or o.get("client_order_id") == order_id:
                o["status"] = status
                o["cancellable"] = False
                if status == "TRADED":
                    o["filled_qty"] = o.get("qty")
                    o["filled_quantity"] = o.get("qty")
                return o
        return None

    def cancel(self, order_id: str) -> Dict[str, Any]:
        for o in self.orders:
            if o.get("order_id") == order_id or o.get("client_order_id") == order_id:
                st = str(o.get("status") or "").upper()
                if st in ("TRADED", "FILLED"):
                    return {"accepted": False, "code": "ALREADY_FILLED", "order_id": order_id, "message": "Order already filled. Check Active trades."}
                if st == "CANCELLED":
                    return {"accepted": False, "code": "ORDER_NOT_FOUND", "order_id": order_id, "message": "Order not found. Nothing was cancelled."}
                o["status"] = "CANCELLED"
                o["cancellable"] = False
                return {"accepted": True, "code": "OK", "order_id": order_id, "message": None, "result": {"order_id": order_id}}
        return {"accepted": False, "code": "ORDER_NOT_FOUND", "order_id": order_id, "message": "Order not found. Nothing was cancelled."}

    def trades_today(self) -> Dict[str, Any]:
        trades = [dict(t) for t in self.trades]
        realized_rows = [t for t in trades if t.get("exit_reason") not in ("open", "") and t.get("realized_pnl") is not None]
        total = round(sum(float(t["realized_pnl"]) for t in realized_rows), 2)
        total_net = round(sum(float(t.get("net_pnl") or 0) for t in realized_rows), 2)
        return {
            "day": self.day,
            "trades": trades,
            "total_realized_pnl": total,
            "total_costs": 0,
            "total_net_pnl": total_net,
            "trade_count": len(trades),
            "closed_count": len(realized_rows),
            "lots_traded": int(sum(int(t.get("lots") or 0) for t in trades)),
        }

    def signals_today(self) -> Dict[str, Any]:
        sigs = [dict(s) for s in self.signals]
        return {"day": self.day, "signals": sigs, "count": len(sigs)}

    def unrealized_sum(self) -> float:
        return round(sum(float(p.get("unrealized_pnl") or 0) for p in self.positions.values()), 2)

    def realized_sum(self) -> float:
        return round(sum(self.realized.values()), 2)

    def position_rows(self) -> List[dict]:
        return [dict(p) for p in self.positions.values() if int(p.get("qty") or 0) != 0]

    def find_event_position(self, event_id: str) -> Optional[Dict[str, Any]]:
        for p in self.positions.values():
            if p.get("event_id") == event_id or p.get("tape_signal_id") == event_id:
                return dict(p)
        return None
