"""D2: GET research/g5 reads G5_TRACKER.json with soft-fail."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.books.adapters import BookPaths
from app.research import g5 as research_g5


class TestResearchG5(unittest.TestCase):
    def test_missing_soft_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = BookPaths("NIFTY", root, "c.yaml", root / "shadow")
            (root / "shadow").mkdir(parents=True)
            payload = research_g5.g5_payload([book])
        self.assertEqual(len(payload["books"]), 1)
        self.assertIn("missing", payload["errors"][0])
        self.assertEqual(payload["books"][0]["underlying"], "NIFTY")
        self.assertIsNone(payload["books"][0]["gate_G5"])
        self.assertEqual(payload["books"][0]["sessions"], [])

    def test_normalize_and_truncate_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            shadow.mkdir(parents=True)
            sessions = [{"day": f"2026-01-{i:02d}", "has_g5_fill": False} for i in range(1, 46)]
            raw = {
                "updated": "2026-08-26T15:27:39",
                "config": "paper_2l_nifty_tier2_recommended",
                "gate_G5": {
                    "target_sessions_with_broker_fill": 20,
                    "sessions_with_g5_fill": 2,
                    "pass": False,
                    "remaining": 18,
                },
                "lab_coverage": {"n_days": 45},
                "slippage_vs_lab": {},
                "sessions": sessions,
                "how_to_log_broker_fill": {"manual": "secret-ish path"},
            }
            (shadow / "G5_TRACKER.json").write_text(json.dumps(raw), encoding="utf-8")
            book = BookPaths("NIFTY", root, "c.yaml", shadow)
            payload = research_g5.g5_payload([book], sessions_cap=40)

        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["updated"], "2026-08-26T15:27:39")
        row = payload["books"][0]
        self.assertEqual(row["underlying"], "NIFTY")
        self.assertEqual(row["config"], "paper_2l_nifty_tier2_recommended")
        self.assertEqual(row["gate_G5"]["sessions_with_g5_fill"], 2)
        self.assertEqual(len(row["sessions"]), 40)
        self.assertTrue(row["sessions_truncated"])
        self.assertEqual(row["sessions"][0]["day"], "2026-01-06")
        self.assertEqual(row["sessions"][-1]["day"], "2026-01-45")
        self.assertNotIn("how_to_log_broker_fill", row)

    def test_filter_underlying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            n = BookPaths("NIFTY", root, "c.yaml", root / "n")
            b = BookPaths("BANKNIFTY", root, "c.yaml", root / "b")
            (root / "n").mkdir()
            (root / "b").mkdir()
            payload = research_g5.g5_payload([n, b], underlying="BANKNIFTY")
        self.assertEqual([x["underlying"] for x in payload["books"]], ["BANKNIFTY"])


if __name__ == "__main__":
    unittest.main()
