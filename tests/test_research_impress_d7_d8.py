"""D7 cost-honesty + scale; D8 brief."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.books.adapters import BookPaths
from app.research import brief as research_brief
from app.research import cost as research_cost
from app.research import scale as research_scale


class TestResearchImpressD7D8(unittest.TestCase):
    def test_cost_honesty_aggregates_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "reports"
            path.mkdir(parents=True)
            csv = (
                "variant,ym,n_trades,month_net_pnl,sum_explained_drag,sum_fo_cost,sum_est_spread,dd_pct,lot_size_used\n"
                "clean_25pct_2l,2026-01,2,100.0,10.0,5.0,4.0,1.0,30\n"
                "clean_25pct_2l,2026-02,3,-50.0,20.0,8.0,6.0,2.0,30\n"
                "clean_25pct_20l,2026-01,9,999.0,1.0,1.0,1.0,0.0,30\n"
            )
            (path / "clean_25pct_cost_verify_months.csv").write_text(csv, encoding="utf-8")
            payload = research_cost.cost_honesty_payload(
                nifty_root=root, bn_root=root, underlying="BANKNIFTY"
            )
        self.assertTrue(payload["available"])
        self.assertEqual(payload["summary"]["n_trades"], 5)
        self.assertEqual(payload["summary"]["net_pnl"], 50.0)
        self.assertEqual(payload["summary"]["explained_drag"], 30.0)
        self.assertEqual(len(payload["months"]), 2)

    def test_cost_nifty_soft_empty(self) -> None:
        payload = research_cost.cost_honesty_payload(
            nifty_root=Path("."), bn_root=Path("."), underlying="NIFTY"
        )
        self.assertFalse(payload["available"])
        self.assertEqual(payload["errors"], [])

    def test_scale_rows_no_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "reports"
            path.mkdir(parents=True)
            raw = {
                "meta": {"span": "2021-07->2026-06", "recipe": "clean"},
                "runs": [
                    {
                        "id": "clean_25pct_2l",
                        "capital": 200000,
                        "max_premium_frac": 0.25,
                        "premium_budget": 50000,
                        "investor": {
                            "AUM": 200000,
                            "deploy_pct": 25,
                            "return_pct": 153.79,
                            "peak_dd_pct": 23.52,
                            "net_pnl": 307571.4,
                            "n_trades": 100,
                            "green_pct": 57.9,
                        },
                        "trades": [{"x": 1}] * 100,
                    }
                ],
            }
            (path / "clean_25pct_gap300_scale.json").write_text(json.dumps(raw), encoding="utf-8")
            payload = research_scale.scale_payload(
                nifty_root=root, bn_root=root, underlying="BANKNIFTY"
            )
        self.assertTrue(payload["available"])
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["aum"], 200000.0)
        self.assertNotIn("trades", payload["rows"][0])
        blob = json.dumps(payload)
        self.assertNotIn('"trades"', blob)

    def test_brief_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            shadow.mkdir()
            day = "2026-08-26"
            (shadow / f"TRADE_CARD_{day}.md").write_text("# card\n- ok\n", encoding="utf-8")
            book = BookPaths("NIFTY", root, "c.yaml", shadow)
            payload = research_brief.brief_payload([book], day=day)
        self.assertEqual(payload["day"], day)
        self.assertTrue(payload["books"][0]["exists"])
        self.assertIn("card", payload["books"][0]["markdown"] or "")
        self.assertEqual(payload["errors"], [])


if __name__ == "__main__":
    unittest.main()
