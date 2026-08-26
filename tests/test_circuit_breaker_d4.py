"""D4: circuit-breaker GET read model."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.books.adapters import BookPaths, circuit_from_books


class TestCircuitBreakerD4(unittest.TestCase):
    def _book_with_state(self, root: Path, name: str, state: dict) -> BookPaths:
        shadow = root / name
        shadow.mkdir(parents=True)
        (shadow / "execution_state.json").write_text(json.dumps(state), encoding="utf-8")
        return BookPaths(name, root, "c.yaml", shadow)

    def test_healthy_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nifty = self._book_with_state(
                root,
                "NIFTY",
                {
                    "equity": 98000.0,
                    "peak_equity": 100000.0,
                    "dd_mode": "live",
                    "day_pnl": -120.5,
                    "month_pnl": 4200.0,
                    "month_halted": False,
                    "day_daily_halt": False,
                },
            )
            with patch("app.books.adapters._circuit_limits", return_value={
                "daily_loss_limit_inr": 2000.0,
                "max_drawdown_from_peak_pct": 0.20,
            }):
                payload = circuit_from_books([nifty])

        self.assertFalse(payload["tripped"])
        self.assertFalse(payload["soft_halt"])
        self.assertIsNone(payload["trip_reason"])
        self.assertEqual(payload["peak_dd_pct"], 0.02)
        self.assertEqual(payload["limits"]["daily_loss_limit_inr"], 2000.0)
        self.assertEqual(payload["limits"]["max_drawdown_from_peak_pct"], 0.20)
        row = payload["books"][0]
        self.assertEqual(row["underlying"], "NIFTY")
        self.assertEqual(row["dd_pct"], 0.02)
        self.assertEqual(row["dd_mode"], "live")
        self.assertEqual(row["day_pnl"], -120.5)
        self.assertEqual(row["month_pnl"], 4200.0)

    def test_halted_and_soft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nifty = self._book_with_state(
                root,
                "NIFTY",
                {
                    "equity": 80000.0,
                    "peak_equity": 100000.0,
                    "dd_mode": "halted",
                    "day_pnl": -5000.0,
                    "month_pnl": -8000.0,
                },
            )
            bn = self._book_with_state(
                root,
                "BANKNIFTY",
                {
                    "equity": 200000.0,
                    "peak_equity": 200000.0,
                    "dd_mode": "live",
                    "day_pnl": 0.0,
                    "month_pnl": 0.0,
                    "month_halted": True,
                },
            )
            with patch("app.books.adapters._circuit_limits", return_value={
                "daily_loss_limit_inr": None,
                "max_drawdown_from_peak_pct": 0.20,
            }):
                payload = circuit_from_books([nifty, bn])

        self.assertTrue(payload["tripped"])
        self.assertTrue(payload["soft_halt"])
        self.assertIn("NIFTY", payload["trip_reason"] or "")
        self.assertEqual(payload["peak_dd_pct"], 0.2)
        self.assertEqual(len(payload["books"]), 2)
        self.assertEqual(payload["books"][0]["dd_mode"], "halted")


if __name__ == "__main__":
    unittest.main()
