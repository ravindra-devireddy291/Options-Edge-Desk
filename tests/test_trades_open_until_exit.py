"""Open paper rounds must not look closed from lab planned exit."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.books.adapters import BookPaths, _round_from_journal, trades_today


class TestOpenUntilBrokerExit(unittest.TestCase):
    def test_entry_fill_ignores_lab_eod(self):
        lab = {"entry": 113.16, "exit": 138.8, "exit_reason": "eod", "net_pnl": 15988.25, "status": "ok"}
        fill = {"entry": 113.16, "exit": None, "net_pnl": None, "qty": 650, "notes": "desk_paper_entry"}
        bo = {"side": "BUY", "lots": 10}
        round_ = _round_from_journal(lab, fill, bo)
        self.assertEqual(round_["exit_reason"], "open")
        self.assertIsNone(round_["exit_px"])
        self.assertIsNone(round_["net"])

    def test_broker_exit_closes(self):
        lab = {"entry": 113.16, "exit": 140.0, "exit_reason": "eod", "net_pnl": 999.0}
        fill = {"entry": 113.16, "exit": 138.8, "net_pnl": 15988.25, "exit_reason": "eod_flatten"}
        round_ = _round_from_journal(lab, fill, {})
        self.assertEqual(round_["exit_reason"], "eod_flatten")
        self.assertEqual(round_["exit_px"], 138.8)
        self.assertEqual(round_["net"], 15988.25)

    @patch("app.books.adapters.market_session", return_value="open")
    @patch("app.books.adapters._session_day")
    def test_lab_only_eod_open_during_session(self, mock_day, _mock_sess):
        from datetime import date

        mock_day.return_value = date(2026, 8, 26)
        lab = {"entry": 113.16, "exit": 138.8, "exit_reason": "eod", "net_pnl": 15988.25, "status": "ok"}
        round_ = _round_from_journal(lab, {}, {}, day="2026-08-26")
        self.assertEqual(round_["exit_reason"], "open")
        self.assertIsNone(round_["exit_px"])
        self.assertIsNone(round_["net"])

    @patch("app.books.adapters.market_session", return_value="closed")
    @patch("app.books.adapters._session_day")
    def test_lab_only_eod_closes_after_session(self, mock_day, _mock_sess):
        from datetime import date

        mock_day.return_value = date(2026, 8, 26)
        lab = {"entry": 113.16, "exit": 138.8, "exit_reason": "eod", "net_pnl": 15988.25, "status": "ok"}
        round_ = _round_from_journal(lab, {}, {}, day="2026-08-26")
        self.assertEqual(round_["exit_reason"], "eod")
        self.assertEqual(round_["exit_px"], 138.8)
        self.assertEqual(round_["net"], 15988.25)

    def test_trades_today_marks_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            shadow.mkdir(parents=True)
            day = "2026-08-26"
            row = {
                "ts": f"{day}T06:21:00+05:30",
                "sleeve": "fade",
                "tradeable": True,
                "lab": {
                    "status": "ok",
                    "entry": 113.16,
                    "exit": 138.8,
                    "exit_reason": "eod",
                    "net_pnl": 15988.25,
                    "symbol": "NIFTY-Sep2026-24350-PE",
                    "lots": 10,
                    "lot_size": 65,
                },
                "broker_order": {"side": "BUY", "lots": 10, "client_order_id": "nifty-fade-1"},
                "broker_fill": {
                    "entry": 113.16,
                    "exit": None,
                    "net_pnl": None,
                    "qty": 650,
                    "notes": "desk_paper_entry",
                    "recorded_at": f"{day}T06:21:00Z",
                },
            }
            (shadow / f"shadow_{day}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            book = BookPaths(
                name="NIFTY",
                lab_root=root,
                config_rel="config.yaml",
                shadow_dir=shadow,
            )
            payload = trades_today([book], day)
            self.assertEqual(payload["trade_count"], 1)
            self.assertEqual(payload["closed_count"], 0)
            trade = payload["trades"][0]
            self.assertEqual(trade["exit_reason"], "open")
            self.assertIsNone(trade["exit_price"])
            self.assertIsNone(trade["net_pnl"])

    @patch("app.books.adapters.market_session", return_value="open")
    @patch("app.books.adapters._session_day")
    def test_trades_today_lab_only_eod_open(self, mock_day, _mock_sess):
        from datetime import date

        mock_day.return_value = date(2026, 8, 26)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            shadow.mkdir(parents=True)
            day = "2026-08-26"
            row = {
                "ts": f"{day}T06:21:00+05:30",
                "sleeve": "fade",
                "tradeable": True,
                "lab": {
                    "status": "ok",
                    "entry": 113.16,
                    "exit": 138.8,
                    "exit_reason": "eod",
                    "net_pnl": 15988.25,
                    "symbol": "NIFTY-Sep2026-24350-PE",
                    "lots": 10,
                    "lot_size": 65,
                },
            }
            (shadow / f"shadow_{day}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            book = BookPaths(
                name="NIFTY",
                lab_root=root,
                config_rel="config.yaml",
                shadow_dir=shadow,
            )
            payload = trades_today([book], day)
            self.assertEqual(payload["trade_count"], 0)
            self.assertEqual(payload["closed_count"], 0)
            self.assertEqual(payload["trades"], [])
            self.assertEqual(payload["total_net_pnl"], 0.0)


if __name__ == "__main__":
    unittest.main()
