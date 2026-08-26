"""Lab ok → desk_paper promote."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.books.adapters import BookPaths, trades_today
from app.books.lab_to_paper import promote_day


class TestLabToPaper(unittest.TestCase):
    def test_promote_closed_lab_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            shadow.mkdir(parents=True)
            day = "2026-08-26"
            row = {
                "sleeve": "fade",
                "tradeable": True,
                "lab": {
                    "status": "ok",
                    "entry": 100.0,
                    "exit": 110.0,
                    "net_pnl": 6500.0,
                    "exit_reason": "eod",
                    "qty": 650,
                    "symbol": "NIFTY-TEST",
                },
                "execution": {"lots": 10},
                "broker_fill": None,
            }
            (shadow / f"shadow_{day}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            book = BookPaths("NIFTY", root, "c.yaml", shadow)
            rec = promote_day(book, day)
            self.assertEqual(rec["promoted"], 1)
            payload = trades_today([book], day)
            self.assertEqual(payload["closed_count"], 1)
            self.assertEqual(payload["total_net_pnl"], 6500.0)
            self.assertEqual(payload["trades"][0]["exit_reason"], "eod")


if __name__ == "__main__":
    unittest.main()
