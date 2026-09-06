"""Tests for trailing stop math + session trail raise."""
from __future__ import annotations

import unittest

from app.execution.sessions import maybe_trail_stop, register
from app.execution.trail import effective_stop_px
from app.execution.types import ManagedSession, SessionState


class TestTrailMath(unittest.TestCase):
    def test_trail_tightens_above_floor(self):
        stop = effective_stop_px(
            entry_px=100.0,
            peak_px=130.0,
            stop_pct=0.30,
            trail_pct=0.10,
            trail_activate_pct=0.20,
        )
        self.assertGreater(stop, 70.0)
        self.assertAlmostEqual(stop, 117.0, places=2)

    def test_floor_before_activate(self):
        stop = effective_stop_px(
            entry_px=100.0,
            peak_px=115.0,
            stop_pct=0.30,
            trail_pct=0.10,
            trail_activate_pct=0.20,
        )
        self.assertAlmostEqual(stop, 70.0, places=2)


class TestTrailSession(unittest.TestCase):
    def test_raises_stop_when_ltp_makes_new_peak(self):
        s = ManagedSession(
            client_order_id="t1",
            correlation_id="c1",
            underlying="BANKNIFTY",
            sleeve="fade",
            security_id="123",
            symbol="BN",
            requested_qty=100,
            stop_pct=0.30,
            tp_pct=0.60,
            trail_pct=0.10,
            trail_activate_pct=0.20,
            filled_qty=100,
            avg_entry_px=100.0,
            sl_order_id="SL1",
            state=SessionState.IN_POSITION,
            current_stop_px=70.0,
        )
        register(s)
        import app.execution.sessions as sess_mod

        calls = []

        def _fake_modify(order_id, *, quantity, trigger_price):
            calls.append((order_id, quantity, trigger_price))
            return {"order_id": order_id}

        orig = sess_mod.dhan.modify_sl_trigger
        sess_mod.dhan.modify_sl_trigger = _fake_modify
        try:
            changed = maybe_trail_stop(s, 130.0)
            self.assertTrue(changed)
            self.assertGreater(s.current_stop_px, 70.0)
            self.assertEqual(len(calls), 1)
        finally:
            sess_mod.dhan.modify_sl_trigger = orig


if __name__ == "__main__":
    unittest.main()
