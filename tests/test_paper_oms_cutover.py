"""Paper OMS + G5 per-book live gate."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.books.adapters import BookPaths
from app.books.live_cutover import G5_TARGET, book_uses_dhan, g5_sessions, is_g5_fill
from app import paper_oms


class TestG5Fill(unittest.TestCase):
    def test_desk_paper_counts(self):
        self.assertTrue(is_g5_fill({"entry": 1, "exit": 2, "source": "desk_paper"}))
        self.assertFalse(is_g5_fill({"entry": 1, "exit": 2, "source": "virtual_paper"}))
        self.assertFalse(is_g5_fill({"entry": 1, "exit": 2}))
        self.assertFalse(is_g5_fill({"entry": 1, "exit": 2, "source": "lab_ok"}))
        self.assertFalse(is_g5_fill({"entry": 1, "exit": 2, "notes": "eod"}))
        self.assertTrue(is_g5_fill({"entry": 1, "exit": 2, "notes": "desk_paper_exit"}))


class TestBookUsesDhan(unittest.TestCase):
    def test_paper_until_g5(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            shadow.mkdir(parents=True)
            book = BookPaths("NIFTY", root, "c.yaml", shadow)
            with patch("app.books.live_cutover.get_settings") as gs:
                gs.return_value.live_enabled = True
                gs.return_value.live_nifty = True
                gs.return_value.live_banknifty = False
                self.assertFalse(book_uses_dhan("NIFTY", book))
                # Seed 20 G5 days
                for i in range(G5_TARGET):
                    day = f"2026-07-{i+1:02d}"
                    row = {
                        "sleeve": "fade",
                        "broker_fill": {
                            "entry": 10,
                            "exit": 11,
                            "source": "desk_paper",
                            "net_pnl": 1,
                        },
                    }
                    (shadow / f"shadow_{day}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
                self.assertEqual(g5_sessions(book), G5_TARGET)
                self.assertTrue(book_uses_dhan("NIFTY", book))

    def test_lab_only_rounds_do_not_unlock_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            shadow.mkdir(parents=True)
            book = BookPaths("NIFTY", root, "c.yaml", shadow)
            for i in range(G5_TARGET):
                day = f"2026-07-{i+1:02d}"
                row = {
                    "sleeve": "fade",
                    "broker_fill": {"entry": 10, "exit": 11, "net_pnl": 1},
                }
                (shadow / f"shadow_{day}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(g5_sessions(book), 0)
            with patch("app.books.live_cutover.get_settings") as gs:
                gs.return_value.live_enabled = True
                gs.return_value.live_nifty = True
                gs.return_value.live_banknifty = True
                self.assertFalse(book_uses_dhan("NIFTY", book))


class TestPaperOms(unittest.TestCase):
    def setUp(self):
        paper_oms.reset_for_tests()

    def tearDown(self):
        paper_oms.reset_for_tests()

    def test_buy_then_sell(self):
        buy = paper_oms.apply_buy(
            underlying="NIFTY",
            sleeve="fade",
            security_id="12345",
            symbol="NIFTY-TEST-PE",
            qty=650,
            lots=10,
            lot_size=65,
            price=100.0,
            client_order_id="desk-1",
        )
        self.assertEqual(buy["position"]["qty"], 650)
        grid = paper_oms.positions_grid()
        self.assertEqual(grid["row_count"], 1)
        sell = paper_oms.apply_sell(
            security_id="12345",
            qty=650,
            price=110.0,
            client_order_id="desk-2",
        )
        self.assertTrue(sell["ok"])
        self.assertEqual(sell["realized_pnl"], 6500.0)
        self.assertEqual(paper_oms.positions_grid()["row_count"], 0)


if __name__ == "__main__":
    unittest.main()
