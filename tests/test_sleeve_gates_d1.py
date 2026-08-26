"""D1: sleeve_gates passes through GateDecision headroom fields."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.books.adapters import BookPaths, _public_gate_row, sleeve_gates


class TestSleeveGatesD1(unittest.TestCase):
    def test_public_row_rounds_and_null_reason_when_allow(self) -> None:
        row = _public_gate_row(
            "fade",
            {
                "allow": True,
                "reason": "ok",
                "lots": 10,
                "dd_mode": "live",
                "dd_pct": 0.01812,
                "day_pnl": -120.456,
                "month_pnl": 4200.1,
                "daily_cap": None,
                "monthly_cap": 15000,
                "premium_budget": 25000.009,
                "deploy_frac": 0.25001,
            },
        )
        self.assertEqual(row["sleeve"], "fade")
        self.assertTrue(row["allow"])
        self.assertEqual(row["lots"], 10)
        self.assertIsNone(row["reason"])
        self.assertEqual(row["dd_mode"], "live")
        self.assertEqual(row["dd_pct"], 0.0181)
        self.assertEqual(row["day_pnl"], -120.46)
        self.assertEqual(row["month_pnl"], 4200.1)
        self.assertIsNone(row["daily_cap"])
        self.assertEqual(row["monthly_cap"], 15000.0)
        self.assertEqual(row["premium_budget"], 25000.01)
        self.assertEqual(row["deploy_frac"], 0.25)

    def test_sleeve_gates_preserves_allow_lots_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = BookPaths("NIFTY", root, "c.yaml", root / "shadow")

            def fake_gate(b, *, sleeve, day=None):
                if sleeve == "fade":
                    return {
                        "allow": True,
                        "reason": "ok",
                        "lots": 10,
                        "dd_mode": "live",
                        "dd_pct": 0.018,
                        "day_pnl": -120.5,
                        "month_pnl": 4200.0,
                        "daily_cap": 2000.0,
                        "monthly_cap": 15000.0,
                        "premium_budget": 25000.0,
                        "deploy_frac": 0.25,
                    }
                return {
                    "allow": False,
                    "reason": "ORB is denied after a fade loss",
                    "lots": 0,
                    "dd_mode": "live",
                    "dd_pct": 0.018,
                    "day_pnl": -120.5,
                    "month_pnl": 4200.0,
                    "daily_cap": 2000.0,
                    "monthly_cap": 15000.0,
                    "premium_budget": 25000.0,
                    "deploy_frac": 0.25,
                }

            with patch("app.books.adapters.check_book_gate", side_effect=fake_gate):
                rows = sleeve_gates(book)

        self.assertEqual(len(rows), 2)
        fade, orb = rows
        self.assertEqual(fade["allow"], True)
        self.assertEqual(fade["lots"], 10)
        self.assertIsNone(fade["reason"])
        self.assertEqual(fade["premium_budget"], 25000.0)
        self.assertEqual(orb["allow"], False)
        self.assertEqual(orb["lots"], 0)
        self.assertEqual(orb["reason"], "ORB is denied after a fade loss")
        self.assertEqual(orb["dd_pct"], 0.018)


if __name__ == "__main__":
    unittest.main()
