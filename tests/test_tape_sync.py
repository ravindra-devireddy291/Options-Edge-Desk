"""Tape merge + missing-day window. Does not run compound_book."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from app.research.stable import PackDef
from app.research.tape_sync import clamp_sync_to, merge_tapes, sync_window


def _pack() -> PackDef:
    return PackDef(
        pack_id="nifty_tier2_recommended",
        underlying="NIFTY",
        role="PRIMARY",
        config_rel="c.yaml",
        tape_rel="reports/t.json",
        selection="primary",
    )


class TestTapeSync(unittest.TestCase):
    def test_merge_appends_new_days(self) -> None:
        existing = {
            "trades": [{"day": "2026-06-30", "symbol": "X", "sleeve": "fade", "net_pnl": 1.0}],
            "months": [{"ym": "2026-06", "net_pnl": 1}],
            "investor": {"n_trades": 1, "net_pnl": 1.0},
        }
        incoming = {
            "trades": [
                {"day": "2026-06-30", "symbol": "X", "sleeve": "fade", "net_pnl": 1.0},
                {"day": "2026-07-02", "symbol": "Y", "sleeve": "fade", "net_pnl": 40.5},
            ],
            "months": [{"ym": "2026-07", "net_pnl": 40.5}],
        }
        added = merge_tapes(existing, incoming)
        self.assertEqual(added, 1)
        self.assertEqual(len(existing["trades"]), 2)
        self.assertEqual(existing["investor"]["n_trades"], 2)
        self.assertEqual(existing["investor"]["net_pnl"], 41.5)
    def test_merge_does_not_overwrite_existing_month(self) -> None:
        existing = {
            "trades": [{"day": "2026-06-02", "symbol": "A", "sleeve": "fade", "net_pnl": 100.0}],
            "months": [{"ym": "2026-06", "net_pnl": 100}],
            "investor": {"n_trades": 1, "net_pnl": 100.0, "peak_dd_pct": 23.27},
        }
        incoming = {
            "trades": [{"day": "2026-07-02", "symbol": "B", "sleeve": "fade", "net_pnl": 40.0}],
            "months": [{"ym": "2026-06", "net_pnl": -9999}, {"ym": "2026-07", "net_pnl": 40.0}],
            "investor": {"peak_dd_pct": 53.0},
        }
        merge_tapes(existing, incoming)
        june = next(m for m in existing["months"] if m["ym"] == "2026-06")
        self.assertEqual(june["net_pnl"], 100.0)
        self.assertEqual(existing["investor"]["peak_dd_pct"], 23.27)
        self.assertEqual(existing["investor"]["locked_peak_dd_pct"], 23.27)

    def test_gap_after_june_lock(self) -> None:
        with patch("app.research.tape_sync.tape_last_day", return_value=date(2026, 6, 30)):
            with patch("app.research.tape_sync.tape_cover_day", return_value=date(2026, 6, 30)):
                with patch("app.books.adapters.paper_book_start", return_value=date(2026, 8, 17)):
                    with patch("app.research.tape_sync.session_day", return_value=date(2026, 8, 27)):
                        with patch("app.research.tape_sync.market_session", return_value="closed"):
                            with patch("app.research.tape_sync.tape_net_to_last", return_value=512983.0):
                                gap = sync_window(_pack())
        self.assertEqual(gap["sync_from"], "2026-07-01")
        self.assertEqual(gap["sync_to"], "2026-08-27")
        self.assertTrue(gap["can_sync"])
        self.assertFalse(gap["today_open"])
        self.assertEqual(gap["tape_last_day"], "2026-06-30")
        self.assertEqual(gap["tape_net_pnl"], 512983.0)

    def test_today_blocked_while_session_open(self) -> None:
        with patch("app.research.tape_sync.tape_last_day", return_value=date(2026, 6, 25)):
            with patch("app.research.tape_sync.tape_cover_day", return_value=date(2026, 6, 25)):
                with patch("app.books.adapters.paper_book_start", return_value=date(2026, 8, 17)):
                    with patch("app.research.tape_sync.session_day", return_value=date(2026, 8, 27)):
                        with patch("app.research.tape_sync.market_session", return_value="open"):
                            with patch("app.research.tape_sync.tape_net_to_last", return_value=1.0):
                                gap = sync_window(_pack())
        self.assertEqual(gap["sync_to"], "2026-08-26")
        self.assertTrue(gap["today_open"])

    def test_up_to_date_at_last_closed_day(self) -> None:
        with patch("app.research.tape_sync.tape_last_day", return_value=date(2026, 8, 27)):
            with patch("app.research.tape_sync.tape_cover_day", return_value=date(2026, 8, 27)):
                with patch("app.books.adapters.paper_book_start", return_value=date(2026, 8, 17)):
                    with patch("app.research.tape_sync.session_day", return_value=date(2026, 8, 27)):
                        with patch("app.research.tape_sync.market_session", return_value="closed"):
                            with patch("app.research.tape_sync.tape_net_to_last", return_value=1.0):
                                gap = sync_window(_pack())
        self.assertFalse(gap["can_sync"])
        self.assertIsNone(gap["sync_from"])

    def test_weekend_is_not_missing_days(self) -> None:
        with patch("app.research.tape_sync.tape_last_day", return_value=date(2026, 8, 28)):
            with patch("app.research.tape_sync.tape_cover_day", return_value=date(2026, 8, 28)):
                with patch("app.books.adapters.paper_book_start", return_value=date(2026, 8, 17)):
                    with patch("app.research.tape_sync.session_day", return_value=date(2026, 8, 29)):
                        with patch("app.research.tape_sync.market_session", return_value="closed"):
                            with patch("app.research.tape_sync.tape_net_to_last", return_value=1.0):
                                gap = sync_window(_pack())
        self.assertFalse(gap["can_sync"])

    def test_synced_through_empty_session_disables(self) -> None:
        with patch("app.research.tape_sync.tape_last_day", return_value=date(2026, 8, 26)):
            with patch("app.research.tape_sync.tape_cover_day", return_value=date(2026, 8, 27)):
                with patch("app.books.adapters.paper_book_start", return_value=date(2026, 8, 17)):
                    with patch("app.research.tape_sync.session_day", return_value=date(2026, 8, 28)):
                        with patch("app.research.tape_sync.market_session", return_value="pre"):
                            with patch("app.research.tape_sync.tape_net_to_last", return_value=1.0):
                                gap = sync_window(_pack())
        self.assertFalse(gap["can_sync"])

    def test_clamp_blocks_synced_and_future(self) -> None:
        start = date(2026, 6, 26)
        end = date(2026, 8, 27)
        self.assertIsNone(clamp_sync_to("2026-06-25", start, end))
        self.assertIsNone(clamp_sync_to("2026-08-28", start, end))
        self.assertEqual(clamp_sync_to("2026-08-10", start, end), date(2026, 8, 10))
        self.assertEqual(clamp_sync_to(None, start, end), end)


if __name__ == "__main__":
    unittest.main()
