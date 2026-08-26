"""D6: research/oos normalized windows."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.research import oos as research_oos


class TestResearchOosD6(unittest.TestCase):
    def test_nifty_train_oos_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "reports" / "experiments"
            path.mkdir(parents=True)
            raw = {
                "rows": {
                    "T2_Gate5": {
                        "train": {
                            "id": "anchor_tier2_recommended",
                            "start": "2021-07-01",
                            "end": "2024-12-31",
                            "return_pct": 139.73,
                            "peak_dd_pct": 23.27,
                        },
                        "oos": {
                            "id": "anchor_tier2_recommended",
                            "start": "2025-01-01",
                            "end": "2026-06-30",
                            "return_pct": 114.81,
                            "peak_dd_pct": 37.68,
                        },
                    }
                }
            }
            (path / "nifty_shortlist_oos_confirm.json").write_text(json.dumps(raw), encoding="utf-8")
            payload = research_oos.oos_payload(
                nifty_root=root, bn_root=root, underlying="NIFTY"
            )
        self.assertEqual(payload["underlying"], "NIFTY")
        self.assertEqual(payload["errors"], [])
        ids = [w["id"] for w in payload["windows"]]
        self.assertIn("train", ids)
        self.assertIn("oos", ids)
        train = next(w for w in payload["windows"] if w["id"] == "train")
        self.assertEqual(train["return_pct"], 139.73)
        self.assertEqual(train["verdict"], "pass")
        self.assertIn("→", train["span"])

    def test_bn_halfspan_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "reports" / "experiments"
            path.mkdir(parents=True)
            raw = {
                "baseline_id": "anchor_client_f4o2_gap300_m6",
                "spans": {
                    "2021_h2": ["2021-07-01", "2021-12-31"],
                    "2024_full": ["2024-01-01", "2024-12-31"],
                },
                "ranked": [
                    {
                        "id": "anchor_client_f4o2_gap300_m6",
                        "thesis": "anchor",
                        "pass_both_halfspans": True,
                        "spans": {
                            "2021_h2": {
                                "verdict": "PASS",
                                "return_pct": 33.28,
                                "peak_dd_pct": 1.01,
                            },
                            "2024_full": {
                                "verdict": "PASS",
                                "return_pct": 62.83,
                                "peak_dd_pct": 16.33,
                            },
                        },
                    }
                ],
            }
            (path / "bn_survivors_halfspan.json").write_text(json.dumps(raw), encoding="utf-8")
            payload = research_oos.oos_payload(
                nifty_root=root, bn_root=root, underlying="BANKNIFTY"
            )
        self.assertEqual(payload["underlying"], "BANKNIFTY")
        self.assertEqual(len(payload["windows"]), 2)
        self.assertEqual(payload["windows"][0]["id"], "train")
        self.assertEqual(payload["windows"][1]["verdict"], "pass")

    def test_missing_soft_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = research_oos.oos_payload(
                nifty_root=root, bn_root=root, underlying="NIFTY"
            )
        self.assertTrue(payload["errors"])
        self.assertEqual(payload["windows"], [])


if __name__ == "__main__":
    unittest.main()
