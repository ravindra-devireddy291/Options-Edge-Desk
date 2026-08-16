"""Mock replay engine: clock + tape + ledger. Never talks to Dhan."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, TypeVar

from app.brokers.dhan.contracts import DEFAULT_LOT
from app.mock.clock import DEFAULT_SPEED, SimClock
from app.mock.ledger import MockLedger
from app.mock.marks import index_spot, option_mark
from app.mock.tape_index import load_tape_trades, pick_demo_days, schedule_for_replay
from app.runners.state import RUNNER
from app.session import to_utc_z

T = TypeVar("T")


class MockEngine:
    def __init__(self) -> None:
        self.clock = SimClock(day=date.today())
        self.ledger = MockLedger()
        self.events: List[Dict[str, Any]] = []
        self.execution: str = "manual"
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._fired_entry: set[str] = set()
        self._fired_exit: set[str] = set()
        self._skipped: set[str] = set()
        self._eod_done: bool = False
        self.loaded = False

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind MockLedger.asyncio.Lock to the FastAPI event loop."""
        self._loop = loop
        self.ledger.bind_loop(loop)

    async def exclusive(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Hold the ledger lock, then run fn (REST + ticker share this)."""
        lock = self.ledger.lock
        if lock is None:
            return fn(*args, **kwargs)
        async with lock:
            return fn(*args, **kwargs)

    def exclusive_sync(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Same lock from FastAPI sync (threadpool) routes."""
        lock = self.ledger.lock
        loop = self._loop
        if lock is None or loop is None:
            return fn(*args, **kwargs)

        async def _run() -> T:
            async with lock:
                return fn(*args, **kwargs)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            raise RuntimeError("await MOCK.exclusive(...) from async handlers; do not block the event loop")
        return asyncio.run_coroutine_threadsafe(_run(), loop).result(timeout=30)

    def is_active(self) -> bool:
        return (RUNNER.mode or "").lower() == "mock"

    def start(self, *, execution: str = "manual", speed: float = DEFAULT_SPEED, replay_day: Optional[str] = None) -> Dict[str, Any]:
        trades = load_tape_trades()
        day_s, source = pick_demo_days(trades)
        if replay_day:
            day_s = replay_day
        events = schedule_for_replay(trades, replay_day=day_s, source_days=source)
        day = date.fromisoformat(day_s)
        self.execution = execution if execution in ("manual", "auto") else "manual"
        self.events = events
        self._fired_entry.clear()
        self._fired_exit.clear()
        self._skipped.clear()
        self._eod_done = False
        self.clock.reset(day, speed=speed)
        self.ledger.reset(day_s, events)
        self.loaded = True
        RUNNER.execution = self.execution
        RUNNER.replay_day = day_s
        RUNNER.speed = float(speed)
        self.tick()
        return {"day": day_s, "execution": self.execution, "speed": float(speed), "n_events": len(events)}

    def stop(self) -> None:
        self.clock.pause()

    def discard(self) -> None:
        self.loaded = False
        self.events = []
        self.ledger.reset("", [])
        self.clock.playing = False

    def tick(self) -> None:
        """Active clock step: auto-fills, skip windows, tape exits, EOD square-off.

        Independent of REST polling. Must run under exclusive() / exclusive_sync().
        """
        if not self.loaded:
            return
        now = self.clock.now()
        exec_mode = self.execution
        events = list(self.events)
        marks: Dict[str, float] = {}
        for ev in events:
            marks[ev["symbol"]] = option_mark(ev, now)
            sid = ev["signal_id"]
            if now >= ev["entry_at"] and sid not in self._fired_entry:
                self._fired_entry.add(sid)
                if exec_mode == "auto":
                    self._auto_entry(ev, now)
                # manual: trigger via PENDING signal (already in ledger)
            if exec_mode == "manual" and sid not in self._skipped and sid not in self._fired_exit:
                st = self.ledger.signal_status(sid)
                if st == "PENDING" and now >= ev["skip_at"]:
                    self._skipped.add(sid)
                    self.ledger.set_signal(sid, "SKIPPED", "ignored")
            if now >= ev["exit_at"] and sid not in self._fired_exit:
                pos = self.ledger.find_event_position(sid)
                if pos:
                    self._tape_exit(ev, now)
                elif exec_mode == "manual":
                    st = self.ledger.signal_status(sid)
                    if st == "PENDING":
                        self.ledger.set_signal(sid, "SKIPPED", "ignored")
                self._fired_exit.add(sid)
        self.ledger.mark_all(marks)
        if now >= self.clock.session_close() and not self._eod_done:
            self._eod_done = True
            self._session_square_off()

    def _session_square_off(self) -> None:
        """EOD failsafe: flatten leftover overlay / unsquared lots at last mark."""
        for pos in list(self.ledger.position_rows()):
            qty = int(pos.get("qty") or 0)
            if qty <= 0:
                continue
            lots = int(pos.get("lots") or 0) or 1
            ltp = float(pos.get("ltp") or pos.get("average_price") or 0)
            rec = None
            try:
                rec = self.ledger.sell(
                    underlying=str(pos["underlying"]),
                    symbol=str(pos["symbol"]),
                    lots=lots,
                    lot_size=int(pos.get("lot_size") or 1),
                    qty=qty,
                    price=ltp,
                    reason="session_close",
                    close_source="all",
                )
            except RuntimeError:
                continue
            from app import triggers as trigger_store

            trigger_store.push_fill_notice(
                trigger_id=f"fill-eod-{pos.get('underlying')}-{pos.get('symbol')}",
                kind="sell",
                underlying=str(pos["underlying"]),
                expiry=pos.get("expiry"),
                strike=pos.get("strike"),
                option_type=pos.get("option_type"),
                sleeve=str(pos.get("sleeve") or "fade"),
                lots=lots,
                filled_qty=rec.get("quantity") if rec else qty,
                filled_price=ltp,
                tradingsymbol=str(pos.get("symbol") or ""),
                note="Desk squared off leftover qty at session close.",
                side="SELL",
            )

    def _auto_entry(self, ev: Dict[str, Any], now: datetime) -> None:
        px = option_mark(ev, now)
        self.ledger.open_buy(
            ev=ev,
            underlying=ev["underlying"],
            symbol=ev["symbol"],
            security_id=ev["security_id"],
            expiry=ev["expiry"],
            strike=ev["strike"],
            option_type=ev["option_type"],
            sleeve=ev["sleeve"],
            lots=int(ev["lots"]),
            lot_size=int(ev["lot_size"]),
            price=px,
            origin="tape",
            tape_signal_id=ev["signal_id"],
            tape_exit_reason=ev["exit_reason"],
            tape_exit_px=ev["exit"],
            event_id=ev["signal_id"],
        )
        self.ledger.set_signal(ev["signal_id"], "EXECUTED", "auto")
        RUNNER.orders_executed += 1
        from app import triggers as trigger_store

        trigger_store.push_fill_notice(
            trigger_id=f"fill-{ev['signal_id']}-entry",
            kind="buy",
            underlying=ev["underlying"],
            expiry=ev.get("expiry"),
            strike=ev.get("strike"),
            option_type=ev.get("option_type"),
            sleeve=ev.get("sleeve") or "fade",
            lots=int(ev["lots"]),
            filled_qty=int(ev["lots"]) * int(ev["lot_size"]),
            filled_price=px,
            tradingsymbol=str(ev.get("symbol") or ""),
            side="BUY",
        )

    def _tape_exit(self, ev: Dict[str, Any], now: datetime) -> None:
        px = option_mark(ev, now)
        pos = self.ledger.find_event_position(ev["signal_id"])
        if not pos:
            return
        tape_qty = int(pos.get("tape_qty") or 0)
        if tape_qty <= 0:
            return
        lot_size = int(pos.get("lot_size") or ev["lot_size"] or 1)
        rec = None
        try:
            rec = self.ledger.sell(
                underlying=ev["underlying"],
                symbol=ev["symbol"],
                lots=max(1, tape_qty // max(1, lot_size)),
                lot_size=lot_size,
                qty=tape_qty,
                price=px,
                reason=str(ev.get("exit_reason") or "take_profit"),
                lab_exit=float(ev.get("exit") or px),
                close_source="tape",
            )
        except RuntimeError:
            return
        from app import triggers as trigger_store

        trigger_store.push_fill_notice(
            trigger_id=f"fill-{ev['signal_id']}-exit",
            kind="sell",
            underlying=ev["underlying"],
            expiry=ev.get("expiry"),
            strike=ev.get("strike"),
            option_type=ev.get("option_type"),
            sleeve=ev.get("sleeve") or pos.get("sleeve") or "fade",
            lots=tape_qty // max(1, lot_size),
            filled_qty=rec.get("quantity") or tape_qty,
            filled_price=px,
            tradingsymbol=str(ev.get("symbol") or ""),
            note="Desk sold tape lots. Overlay qty left open.",
            side="SELL",
        )

    def replay(self) -> Dict[str, Any]:
        return self.clock.snapshot()

    def spots(self) -> Dict[str, Dict[str, Optional[float]]]:
        now = self.clock.now()
        return {
            "NIFTY": index_spot(self.events, "NIFTY", now, 18000.0),
            "BANKNIFTY": index_spot(self.events, "BANKNIFTY", now, 35000.0),
        }

    def quote_option(
        self,
        *,
        security_id: Optional[str] = None,
        underlying: Optional[str] = None,
        expiry: Optional[str] = None,
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = self.clock.now()
        hit = None
        for ev in self.events:
            if security_id and str(ev.get("security_id")) == str(security_id):
                hit = ev
                break
            if (
                underlying
                and ev["underlying"] == underlying.upper()
                and strike is not None
                and abs(float(ev["strike"]) - float(strike)) < 0.01
                and str(ev["option_type"]).upper() == str(option_type or "").upper()
            ):
                hit = ev
                break
        if hit is None:
            # open position?
            for p in self.ledger.position_rows():
                if security_id and p.get("security_id") == security_id:
                    ltp = float(p.get("ltp") or 0)
                    return {
                        "underlying": p["underlying"],
                        "expiry": p.get("expiry"),
                        "strike": p.get("strike"),
                        "option_type": p.get("option_type"),
                        "security_id": p.get("security_id"),
                        "tradingsymbol": p.get("symbol"),
                        "lot_size": p.get("lot_size"),
                        "ltp": ltp,
                        "bid": ltp,
                        "ask": ltp,
                        "quoted_at": to_utc_z(now),
                        "stale": False,
                    }
            return {
                "underlying": (underlying or "").upper() if underlying else None,
                "expiry": expiry,
                "strike": strike,
                "option_type": option_type,
                "security_id": security_id,
                "tradingsymbol": None,
                "lot_size": DEFAULT_LOT.get((underlying or "NIFTY").upper(), 65),
                "ltp": None,
                "bid": None,
                "ask": None,
                "quoted_at": to_utc_z(now),
                "stale": True,
            }
        ltp = option_mark(hit, now)
        return {
            "underlying": hit["underlying"],
            "expiry": hit["expiry"],
            "strike": hit["strike"],
            "option_type": hit["option_type"],
            "security_id": hit["security_id"],
            "tradingsymbol": hit["symbol"],
            "lot_size": hit["lot_size"],
            "ltp": ltp,
            "bid": ltp,
            "ask": ltp,
            "quoted_at": to_utc_z(now),
            "stale": False,
        }

    def contracts(self, underlying: str) -> Dict[str, Any]:
        und = underlying.upper()
        rows = [e for e in self.events if e["underlying"] == und]
        spots = self.spots()
        spot = (spots.get(und) or {}).get("ltp")
        strikes = sorted({float(e["strike"]) for e in rows})
        lot = int(DEFAULT_LOT.get(und, 65))
        expiry = self.clock.day.isoformat()
        atm = None
        if strikes:
            ref = float(spot or strikes[len(strikes) // 2])
            atm = min(strikes, key=lambda s: abs(s - ref))
        step = 50.0
        if len(strikes) >= 2:
            step = min(b - a for a, b in zip(strikes, strikes[1:]) if b > a)
        return {
            "underlying": und,
            "spot": spot,
            "lot_size": lot,
            "expiry": expiry,
            "expiries": [expiry],
            "atm_strike": atm,
            "strike_step": step,
            "strikes": strikes or [atm] if atm else [],
        }

    def gates(self, underlying: str) -> Dict[str, Any]:
        und = underlying.upper()
        lot = int(DEFAULT_LOT.get(und, 65))
        lots_fade = 10 if und == "NIFTY" else 4
        lots_orb = 2 if und == "BANKNIFTY" else 0
        sleeves = [
            {"sleeve": "fade", "allow": True, "lots": lots_fade, "reason": None},
            {
                "sleeve": "orb",
                "allow": lots_orb > 0,
                "lots": lots_orb,
                "reason": None if lots_orb > 0 else "ORB is denied after a fade loss",
            },
        ]
        return {
            "trading_active": RUNNER.trading_active(),
            "market_session": self.clock.market_session(),
            "underlying": und,
            "lot_size": lot,
            "sleeves": sleeves,
        }

    def books_snapshot(self) -> List[Dict[str, Any]]:
        rows = self.ledger.position_rows()
        by = {"NIFTY": [], "BANKNIFTY": []}
        for r in rows:
            by.setdefault(r["underlying"], []).append(r)
        out = []
        for und, cap in (("NIFTY", 100_000.0), ("BANKNIFTY", 200_000.0)):
            rs = by.get(und) or []
            mtm = round(sum(float(x.get("unrealized_pnl") or 0) for x in rs), 2)
            lots = int(sum(int(x.get("lots") or 0) for x in rs))
            real = float(self.ledger.realized.get(und) or 0)
            label = "Rs 1L book" if und == "NIFTY" else "Rs 2L book"
            g = self.gates(und)["sleeves"]
            out.append(
                {
                    "underlying": und,
                    "label": label,
                    "capital": cap,
                    "equity": round(cap + real + mtm, 2),
                    "open_mtm": mtm,
                    "open_lots": lots,
                    "halted": False,
                    "gates": g,
                }
            )
        return out

    def match_event(self, *, underlying: str, strike: float, option_type: str) -> Optional[Dict[str, Any]]:
        opt = str(option_type or "").upper()
        for ev in self.events:
            if ev["underlying"] == underlying.upper() and abs(float(ev["strike"]) - float(strike)) < 0.01 and ev["option_type"] == opt:
                return ev
        return None

    def triggers_active(self, acked: set) -> Dict[str, Any]:
        from app import triggers as trigger_store

        fill = trigger_store.newest_fill(acked)
        if fill.get("active"):
            return fill
        if self.execution == "auto":
            return {"active": False, "trigger": None}
        now = self.clock.now()
        pending = []
        for s in self.ledger.signals_today()["signals"]:
            if str(s.get("status") or "").upper() != "PENDING":
                continue
            if s.get("signal_id") in acked:
                continue
            ev = next((e for e in self.events if e["signal_id"] == s["signal_id"]), None)
            if ev and now < ev["entry_at"]:
                continue
            pending.append(s)
        if not pending:
            return {"active": False, "trigger": None}
        row = pending[-1]
        ev = next((e for e in self.events if e["signal_id"] == row["signal_id"]), None)
        ltp = option_mark(ev, now) if ev else row.get("ltp")
        placeable = RUNNER.trading_active() and not RUNNER.kill.active
        return {
            "active": True,
            "trigger": {
                "trigger_id": row["signal_id"],
                "kind": "buy",
                "role": "approval",
                "underlying": row["underlying"],
                "expiry": row.get("expiry"),
                "strike": row.get("target_strike"),
                "option_type": row.get("option_type"),
                "sleeve": row.get("sleeve"),
                "suggested_lots": row.get("target_lots"),
                "ltp": ltp,
                "tradingsymbol": row.get("symbol") or "",
                "note": "Nothing is placed until you confirm.",
                "placeable": placeable,
                "created_at": row.get("created_at"),
                "meta": None if placeable else "Trading halted — cannot place.",
                "filled_qty": None,
                "filled_price": None,
                "side": "BUY",
            },
        }

    def status_fields(self) -> Dict[str, Any]:
        spots = self.spots()
        pos = self.ledger.positions_grid()
        unreal = self.ledger.unrealized_sum()
        realized = self.ledger.realized_sum()
        return {
            "mode": "mock",
            "execution": self.execution,
            "replay": self.replay(),
            "token_ok": True,
            "broker_reachable": True,
            "market_session": self.clock.market_session(),
            "session_label": "NSE 09:15–15:30 IST (mock replay)",
            "available_cash": 185000.0,
            "nifty_spot": (spots["NIFTY"] or {}).get("ltp"),
            "nifty_change_pct": (spots["NIFTY"] or {}).get("change_pct"),
            "banknifty_spot": (spots["BANKNIFTY"] or {}).get("ltp"),
            "banknifty_change_pct": (spots["BANKNIFTY"] or {}).get("change_pct"),
            "open_positions": int(pos.get("row_count") or 0),
            "realized_pnl_today": realized,
            "unrealized_pnl": unreal,
            "today_net": round(realized + unreal, 2),
            "shadow_book_halted": False,
            "halted_underlyings": [],
            "books": self.books_snapshot(),
            "last_sync_at": RUNNER.last_sync_at,
        }


MOCK = MockEngine()
