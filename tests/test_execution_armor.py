"""Tests for execution armor (spread gate, partial SL/TP, chase, OCO, WS parser)."""
from __future__ import annotations

import struct
import time
import unittest
from datetime import datetime, timezone

from app.execution.chase import run_chase_cycle
from app.execution.config import ArmorConfig
from app.execution.dhan_ws_feed import parse_full_packet
from app.execution.freshness import tick_ok
from app.execution.spread_chaser import next_limit_price
from app.execution.sessions import handle_order_update, register
from app.execution.types import DhanOrderStatus, DhanOrderUpdate, DepthSnapshot, ManagedSession, SessionState


class TestSpreadGate(unittest.TestCase):
    def test_refuse_wide_spread(self):
        cfg = ArmorConfig(max_spread_pct=0.03)
        d = DepthSnapshot("1", "X", bid=100.0, ask=110.0, ltp=105.0, ts=datetime.now(timezone.utc))
        q = next_limit_price(d, cfg)
        self.assertTrue(q.refused)

    def test_sell_limit_below_ask(self):
        cfg = ArmorConfig(max_spread_pct=0.05, initial_offset_ticks=1, tick_size=0.05)
        d = DepthSnapshot("1", "X", bid=100.0, ask=100.20, ltp=100.10, ts=datetime.now(timezone.utc))
        q = next_limit_price(d, cfg, side="sell")
        self.assertFalse(q.refused)
        self.assertLessEqual(q.limit_px, 100.20)
        self.assertGreaterEqual(q.limit_px, 100.05)


class TestFreshness(unittest.TestCase):
    def test_stale(self):
        old = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 3, tz=timezone.utc)
        self.assertFalse(tick_ok(old, max_age_ms=500))


class TestPartialFillSL(unittest.TestCase):
    def test_partial_sizes_sl_and_tp_qty(self):
        s = ManagedSession(
            client_order_id="c1",
            correlation_id="corr1",
            underlying="NIFTY",
            sleeve="fade",
            security_id="123",
            symbol="NIFTYPE",
            requested_qty=650,
            stop_pct=0.30,
            tp_pct=0.50,
            entry_order_id="E1",
        )
        register(s)
        upd = DhanOrderUpdate(
            order_id="E1",
            status=DhanOrderStatus.PART_TRADED,
            qty=650,
            traded_qty=260,
            remaining_qty=390,
            avg_traded_price=120.0,
            price=119.5,
            trigger_price=0.0,
        )
        import app.execution.sessions as sess_mod

        sl_calls = []
        tp_calls = []

        def _fake_sl(**kw):
            sl_calls.append(kw)
            return {"raw": {"orderId": "SL1"}}

        def _fake_tp(**kw):
            tp_calls.append(kw)
            return {"raw": {"orderId": "TP1"}}

        orig_sl = sess_mod.dhan.place_sl_market
        orig_tp = sess_mod.dhan.place_tp_limit
        sess_mod.dhan.place_sl_market = _fake_sl
        sess_mod.dhan.place_tp_limit = _fake_tp
        try:
            out = handle_order_update(upd)
            self.assertIsNotNone(out)
            assert out is not None
            self.assertIn(out.state, (SessionState.ENTRY_PARTIAL, SessionState.PROTECT_WORKING))
            self.assertEqual(len(sl_calls), 1)
            self.assertEqual(sl_calls[0]["quantity"], 260)
            self.assertEqual(len(tp_calls), 1)
            self.assertEqual(tp_calls[0]["quantity"], 260)
        finally:
            sess_mod.dhan.place_sl_market = orig_sl
            sess_mod.dhan.place_tp_limit = orig_tp


class TestOCO(unittest.TestCase):
    def test_tp_fill_cancels_sl(self):
        s = ManagedSession(
            client_order_id="c2",
            correlation_id="corr2",
            underlying="NIFTY",
            sleeve="fade",
            security_id="123",
            symbol="NIFTYPE",
            requested_qty=650,
            stop_pct=0.30,
            tp_pct=0.50,
            entry_order_id="E2",
            sl_order_id="SL2",
            tp_order_id="TP2",
            filled_qty=650,
            avg_entry_px=100.0,
            state=SessionState.IN_POSITION,
        )
        register(s)
        import app.execution.sessions as sess_mod

        cancelled = []

        def _fake_cancel(oid):
            cancelled.append(oid)
            return {"order_id": oid}

        orig = sess_mod.dhan.cancel_order
        sess_mod.dhan.cancel_order = _fake_cancel
        try:
            upd = DhanOrderUpdate(
                order_id="TP2",
                status=DhanOrderStatus.TRADED,
                qty=650,
                traded_qty=650,
                remaining_qty=0,
                avg_traded_price=150.0,
                price=150.0,
                trigger_price=0.0,
            )
            out = handle_order_update(upd)
            assert out is not None
            self.assertEqual(out.state, SessionState.CLOSED)
            self.assertEqual(out.exit_reason, "tp")
            self.assertIn("SL2", cancelled)
        finally:
            sess_mod.dhan.cancel_order = orig


class TestChaseTimeout(unittest.TestCase):
    def test_zero_fill_aborts(self):
        s = ManagedSession(
            client_order_id="c3",
            correlation_id="corr3",
            underlying="NIFTY",
            sleeve="fade",
            security_id="999",
            symbol="X",
            requested_qty=65,
            stop_pct=0.30,
            tp_pct=0.50,
            entry_order_id="E3",
            limit_px=100.0,
            meta={"leg_role": "entry", "chase_deadline_ts": time.time() - 1},
        )
        register(s)
        import app.execution.chase as chase_mod

        cancelled = []

        def _fake_cancel(oid):
            cancelled.append(oid)
            return {}

        orig = chase_mod.dhan.cancel_order
        chase_mod.dhan.cancel_order = _fake_cancel
        try:
            run_chase_cycle()
            self.assertEqual(s.state, SessionState.ABORTED)
            self.assertIn("E3", cancelled)
        finally:
            chase_mod.dhan.cancel_order = orig


class TestFullPacketParser(unittest.TestCase):
    def test_parse_minimal_full(self):
        buf = bytearray(162)
        buf[0] = 8
        struct.pack_into("<I", buf, 5, 44118)
        struct.pack_into("<f", buf, 8, 150.25)
        struct.pack_into("<i", buf, 14, int(datetime.now(timezone.utc).timestamp()))
        struct.pack_into("<iiHHff", buf, 62, 100, 0, 1, 1, 150.20, 150.30)
        depth = parse_full_packet(bytes(buf))
        self.assertIsNotNone(depth)
        assert depth is not None
        self.assertEqual(depth.security_id, "44118")
        self.assertAlmostEqual(depth.ltp, 150.25, places=2)


if __name__ == "__main__":
    unittest.main()
