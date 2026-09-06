"""Background WS keepers + chase/reconcile loops for execution armor."""
from __future__ import annotations

import asyncio
from typing import List, Optional, Set, Tuple

from app.brokers.dhan import client as dhan
from app.brokers.dhan.client import BN_SECURITY_ID, NIFTY_SECURITY_ID, SEGMENT_INDEX, SEGMENT_OPT
from app.execution.chase import run_chase_cycle
from app.execution.config import ARMOR
from app.execution.dhan_ws_feed import run_feed
from app.execution.dhan_ws_orders import run_order_updates
from app.execution.reconcile import reconcile_open_sessions
from app.execution.sessions import all_open, handle_order_update
from app.runners.state import RUNNER


def _on_depth(depth) -> None:
    try:
        from app.mark_stream import note_depth

        note_depth(depth)
    except Exception:
        pass
    try:
        from app.execution.sessions import trail_open_sessions

        if depth is not None and getattr(depth, "ltp", 0) > 0:
            trail_open_sessions(str(depth.security_id), float(depth.ltp))
    except Exception:
        pass


class ExecutionRunner:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._feed_task: Optional[asyncio.Task] = None
        self._order_task: Optional[asyncio.Task] = None
        self._chase_task: Optional[asyncio.Task] = None
        self._reconcile_task: Optional[asyncio.Task] = None
        self._subscribed: Set[str] = set()
        self._feed_key: str = ""

    def _feed_should_run(self) -> bool:
        return (RUNNER.mode or "").lower() in ("paper", "live")

    def _armor_should_run(self) -> bool:
        return self._feed_should_run() and RUNNER.trading_active()

    def _instruments(self) -> List[Tuple[str, str]]:
        ids: Set[str] = set(self._subscribed)
        for s in all_open():
            if s.security_id:
                ids.add(str(s.security_id))
        try:
            from app.mark_stream import tracked_security_ids

            ids.update(tracked_security_ids())
        except Exception:
            pass
        try:
            from app import paper_oms

            for row in paper_oms.positions_grid().get("rows") or []:
                sid = str(row.get("security_id") or "").strip()
                if sid:
                    ids.add(sid)
        except Exception:
            pass
        out: List[Tuple[str, str]] = [
            (SEGMENT_INDEX, NIFTY_SECURITY_ID),
            (SEGMENT_INDEX, BN_SECURITY_ID),
        ]
        index_ids = {NIFTY_SECURITY_ID, BN_SECURITY_ID}
        for sid in sorted(ids):
            if sid and sid not in index_ids:
                out.append((SEGMENT_OPT, sid))
        return out

    def _instrument_key(self) -> str:
        return ",".join(f"{seg}:{sid}" for seg, sid in self._instruments())

    async def subscribe(self, security_id: str) -> None:
        self._subscribed.add(str(security_id))
        if self._feed_should_run():
            await self.ensure_started()

    async def _restart_feed(self) -> None:
        inst = self._instruments()
        key = self._instrument_key()
        if self._feed_task is not None and not self._feed_task.done() and key == self._feed_key:
            return
        if self._feed_task is not None and not self._feed_task.done():
            self._feed_task.cancel()
            try:
                await self._feed_task
            except asyncio.CancelledError:
                pass
        self._feed_key = key
        if inst:
            self._feed_task = asyncio.create_task(
                run_feed(inst, on_depth=_on_depth, stop=self._stop)
            )

    async def ensure_started(self) -> None:
        if not self._feed_should_run():
            return
        await self._restart_feed()
        if not self._armor_should_run():
            return
        if self._order_task is None or self._order_task.done():
            self._order_task = asyncio.create_task(
                run_order_updates(on_order=handle_order_update, stop=self._stop)
            )
        if ARMOR.enabled and (self._chase_task is None or self._chase_task.done()):
            self._chase_task = asyncio.create_task(self._chase_loop())
        if ARMOR.enabled and (self._reconcile_task is None or self._reconcile_task.done()):
            self._reconcile_task = asyncio.create_task(self._reconcile_loop())

    async def _chase_loop(self) -> None:
        interval = max(0.2, float(ARMOR.chase_interval_ms) / 1000.0)
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(run_chase_cycle)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

    async def _reconcile_loop(self) -> None:
        interval = max(5.0, float(ARMOR.reconcile_interval_s))
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(reconcile_open_sessions)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        for t in (self._feed_task, self._order_task, self._chase_task, self._reconcile_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._feed_task = None
        self._order_task = None
        self._chase_task = None
        self._reconcile_task = None
        self._feed_key = ""
        self._stop = asyncio.Event()

    async def keeper(self) -> None:
        """Lifespan task: market feed while paper/live; armor loops while armed."""
        while True:
            try:
                if self._feed_should_run():
                    try:
                        await asyncio.to_thread(dhan.ensure_fresh_token)
                    except Exception:
                        pass
                    await self.ensure_started()
                elif self._feed_task or self._order_task or self._chase_task or self._reconcile_task:
                    await self.stop()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(2.0)


EXECUTION = ExecutionRunner()
