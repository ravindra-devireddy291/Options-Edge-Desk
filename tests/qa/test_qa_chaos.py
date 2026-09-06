"""QA chaos: crash recovery, idempotency, trail floor, lot floor."""
from __future__ import annotations

import random
import unittest

from app import idempotency, paper_oms
from app.execution.trail import effective_stop_px, floor_stop_px, trail_active


class TestPaperOmsCrash(unittest.TestCase):
    def setUp(self) -> None:
        paper_oms.reset_for_tests()

    def tearDown(self) -> None:
        paper_oms.reset_for_tests()

    def test_reload_rebuilds_open_position(self) -> None:
        paper_oms.apply_buy(
            underlying="NIFTY",
            sleeve="fade",
            security_id="sid-1",
            symbol="NIFTY-QA-PE",
            qty=650,
            lots=10,
            lot_size=65,
            price=100.0,
            client_order_id="desk-qa-1",
        )
        on_disk = paper_oms._load()
        self.assertIn("sid-1", on_disk["positions"])
        grid = paper_oms.positions_grid()
        self.assertEqual(grid["row_count"], 1)
        self.assertEqual(int(grid["rows"][0]["qty"]), 650)

    def test_corrupt_ledger_starts_empty_not_crash(self) -> None:
        path = paper_oms._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        data = paper_oms._load()
        self.assertEqual(data["positions"], {})
        self.assertEqual(data["orders"], [])


class TestIdempotency(unittest.TestCase):
    def test_same_trace_returns_original(self) -> None:
        idempotency.put("qa-trace-1", {"accepted": True, "code": "OK"})
        hit = idempotency.get("qa-trace-1")
        self.assertEqual(hit["code"], "OK")
        self.assertIsNone(idempotency.get(""))
        self.assertIsNone(idempotency.get("missing"))

    def test_auto_ttl_is_longer(self) -> None:
        idempotency.put("auto:qa-1", {"accepted": True})
        self.assertIsNotNone(idempotency.get("auto:qa-1"))


class TestTrailProperties(unittest.TestCase):
    def test_stop_never_below_floor(self) -> None:
        rng = random.Random(7)
        for _ in range(200):
            entry = rng.uniform(20.0, 400.0)
            peak = entry * rng.uniform(1.0, 2.5)
            stop_pct = 0.30
            trail_pct = 0.20
            act = 0.20
            floor = floor_stop_px(entry, stop_pct)
            px = effective_stop_px(
                entry_px=entry,
                peak_px=peak,
                stop_pct=stop_pct,
                trail_pct=trail_pct,
                trail_activate_pct=act,
            )
            self.assertGreaterEqual(px, floor - 1e-9)
            if trail_active(entry, peak, act):
                self.assertGreaterEqual(px, peak * (1.0 - trail_pct) - 1e-9)

    def test_freak_tick_does_not_drop_floor(self) -> None:
        # 500-pt spike then revert: stop stays at trail of the peak, never below floor.
        entry = 100.0
        after_spike = effective_stop_px(
            entry_px=entry, peak_px=600.0, stop_pct=0.30, trail_pct=0.20, trail_activate_pct=0.20
        )
        self.assertGreater(after_spike, 70.0)
        revert = effective_stop_px(
            entry_px=entry, peak_px=100.0, stop_pct=0.30, trail_pct=0.20, trail_activate_pct=0.20
        )
        self.assertAlmostEqual(revert, 70.0, places=2)


class TestLotFloor(unittest.TestCase):
    def test_yaml_lots_never_zero_when_healthy(self) -> None:
        from app.auth import get_settings
        from app.research.stable import PAPER_VARIANTS, yaml_allocation

        get_settings.cache_clear()
        s = get_settings()
        for pack in PAPER_VARIANTS:
            root = s.nifty_lab_root if pack.underlying == "NIFTY" else s.bn_lab_root
            raw = yaml_allocation(root / pack.config_rel)
            fade = int(raw.get("fade_lots") or 0)
            orb = int(raw.get("orb_lots") or 0)
            self.assertGreater(fade + orb, 0, pack.pack_id)
            self.assertGreaterEqual(fade, 1, pack.pack_id)


if __name__ == "__main__":
    unittest.main()
