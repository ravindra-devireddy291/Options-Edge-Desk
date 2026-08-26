"""D3: rejected / last-cycle decision-log row shape."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.books.adapters import BookPaths, last_cycle_signals, rejected_only


class TestSignalsRejectedD3(unittest.TestCase):
    def test_rejected_row_shape_and_lab_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            shadow.mkdir(parents=True)
            day = "2026-08-26"
            rows = [
                {
                    "ts": "2026-08-26T15:27:39",
                    "sleeve": "fade",
                    "tradeable": True,
                    "lab": {
                        "day": day,
                        "status": "ok",
                        "symbol": "NIFTY-Sep2026-24350-PE",
                        "side": "PE",
                        "strike": 24350,
                        "qty": 650,
                    },
                    "execution": {"allow": True, "reason": "ok", "lots": 10},
                    "broker_fill": {"entry": 1, "exit": 2},
                },
                {
                    "ts": "2026-08-26T15:27:39",
                    "sleeve": "orb",
                    "tradeable": False,
                    "lab": {"day": day, "status": "skip_lots_zero", "net_pnl": 0.0},
                    "execution": {"allow": False, "reason": "lots_zero", "lots": 0},
                    "broker_fill": None,
                },
                {
                    "ts": "2026-08-25T04:00:00Z",
                    "sleeve": "fade",
                    "tradeable": False,
                    "lab": {"day": "2026-08-25", "status": "ok", "symbol": "NIFTY-X"},
                    "execution": {"allow": False, "reason": "daily_cap", "lots": 0, "notes": "cap hit"},
                },
            ]
            (shadow / f"shadow_{day}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8",
            )
            book = BookPaths("NIFTY", root, "c.yaml", shadow)
            payload = rejected_only([book])
            cycle = last_cycle_signals([book])

        self.assertEqual(payload["count"], 2)
        skip, gate = payload["rows"]
        for key in ("trace_id", "underlying", "sleeve", "stage", "reason", "symbol", "at", "notes"):
            self.assertIn(key, skip)
            self.assertIn(key, gate)

        self.assertEqual(skip["sleeve"], "orb")
        self.assertEqual(skip["stage"], "signal")
        self.assertEqual(skip["reason"], "skip_lots_zero")
        self.assertIsNone(skip["symbol"])
        self.assertTrue(str(skip["at"]).endswith("Z") or "T" in str(skip["at"]))

        self.assertEqual(gate["stage"], "gate")
        self.assertEqual(gate["reason"], "daily_cap")  # status ok → execution reason
        # wait - _reject_reason: status is "ok" so it falls through to execution.reason "daily_cap"
        # Actually status is "ok" and tradeable false - reason from execution is daily_cap. Good.
        self.assertEqual(gate["notes"], "cap hit")
        self.assertEqual(gate["symbol"], "NIFTY-X")

        # No secret-ish keys
        blob = json.dumps(payload).lower()
        for bad in ("access_token", "totp", "desk_api_key", '"pin"'):
            self.assertNotIn(bad, blob)

        self.assertEqual(len(cycle["rejected"]), 2)
        self.assertEqual(cycle["funnel"]["approved"], 1)
        self.assertEqual(cycle["rejected"][0]["reason"], "skip_lots_zero")


if __name__ == "__main__":
    unittest.main()
