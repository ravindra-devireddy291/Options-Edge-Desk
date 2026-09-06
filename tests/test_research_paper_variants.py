"""Paper research board: 4 variants, YAML allocation, no invented tape."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.research.stable import (
    PAPER_VARIANTS,
    PackDef,
    load_paper_variant,
    stable_catalog,
    yaml_allocation,
)


NIFTY_YAML = """
name: nifty_paper_2l_tier2_recommended
status: client_locked
total_capital_inr: 200000
max_premium_frac: 0.30
max_premium_inr: 60000
max_lots: 10
lots_schedule:
  healthy: { fade: 10, orb: 0 }
backtest_snapshot:
  span: "2021-07-01→2026-06-30"
  return_pct: 256.49
  peak_dd_pct: 23.27
  n_trades: 241
  net_pnl_inr: 512983
"""

BN_YAML = """
name: bn_paper_2l_f6o3_sm400_mce2
board_id: B_f6o3_sm400_mce2
total_capital_inr: 200000
max_premium_frac: 0.25
max_premium_inr: 50000
max_lots: 9
lots_schedule:
  healthy: { fade: 6, orb: 3 }
backtest_snapshot:
  return_pct: 258.44
  peak_dd_pct: 25.44
  n_trades: 481
  net_pnl_inr: 516876
"""


class TestPaperVariants(unittest.TestCase):
    def test_yaml_allocation_reads_capital_lots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.yaml"
            path.write_text(NIFTY_YAML, encoding="utf-8")
            raw = yaml_allocation(path)
        self.assertEqual(raw["total_capital_inr"], 200000.0)
        self.assertEqual(raw["max_lots"], 10)
        self.assertEqual(raw["fade_lots"], 10)
        self.assertEqual(raw["backtest_snapshot"]["n_trades"], 241.0)

    def test_yaml_variant_without_tape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config" / "rungs"
            cfg.mkdir(parents=True)
            (cfg / "bn_alpha.yaml").write_text(BN_YAML, encoding="utf-8")
            pack = PackDef(
                pack_id="bn_f6o3_sm400_mce2",
                underlying="BANKNIFTY",
                role="BN Alpha · Gate 5 paper",
                config_rel="config/rungs/bn_alpha.yaml",
                tape_rel="",
                selection="primary",
            )
            row = load_paper_variant(root, pack)
        self.assertEqual(row["metrics_source"], "yaml_snapshot")
        self.assertFalse(row["tape_exists"])
        self.assertEqual(row["allocation"]["capital"], 200000.0)
        self.assertEqual(row["allocation"]["max_lots"], 9)
        self.assertEqual(row["metrics"]["n_trades"], 481)
        self.assertEqual(row["chart"]["count"], 0)

    def test_catalog_marks_armed_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in (
                "config/rungs/nifty_alpha.yaml",
                "config/rungs/nifty_stable.yaml",
                "config/rungs/bn_alpha.yaml",
                "config/rungs/bn_stable.yaml",
            ):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(NIFTY_YAML if "nifty" in rel else BN_YAML, encoding="utf-8")
            payload = stable_catalog(
                nifty_root=root,
                bn_root=root,
                nifty_config="config/rungs/nifty_alpha.yaml",
                bn_config="config/edge_book_2l_dd20.yaml",
            )
        variants = payload["paper_variants"]
        self.assertEqual(len(PAPER_VARIANTS), 4)
        self.assertTrue(all(p.tape_rel.endswith(".json") for p in PAPER_VARIANTS))
        self.assertEqual(len(variants), 4)
        armed = {row["pack_id"]: row["paper_armed"] for row in variants}
        self.assertTrue(armed["nifty_tier2_recommended"])
        self.assertFalse(armed["nifty_ce400_secondary"])
        self.assertFalse(armed["bn_f6o3_sm400_mce2"])
        self.assertEqual(
            payload["desk_armed"]["NIFTY"],
            "config/rungs/nifty_alpha.yaml",
        )
        blob = json.dumps(payload)
        self.assertNotIn("18.4%", blob)

    def test_pack_aliases_resolve(self) -> None:
        from app.research.stable import paper_pack

        self.assertEqual(paper_pack("nifty_alpha").pack_id, "nifty_tier2_recommended")
        self.assertEqual(paper_pack("bn_stable").config_rel, "config/rungs/bn_stable.yaml")
        self.assertTrue(paper_pack("nifty_alpha").config_rel.endswith("nifty_alpha.yaml"))

    def test_stale_tape_yields_yaml_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config" / "rungs"
            cfg.mkdir(parents=True)
            (cfg / "bn_alpha.yaml").write_text(BN_YAML, encoding="utf-8")
            tape = root / "reports"
            tape.mkdir()
            (tape / "bn_trades_f6o3_sm400_mce2_2l.json").write_text(
                json.dumps(
                    {
                        "investor": {
                            "return_pct": 140.0,
                            "peak_dd_pct": 30.0,
                            "net_pnl": 1.0,
                            "n_trades": 1,
                        },
                        "months": [],
                        "summary": {"start_equity": 200000, "end_equity": 200001},
                    }
                ),
                encoding="utf-8",
            )
            pack = PackDef(
                pack_id="bn_f6o3_sm400_mce2",
                underlying="BANKNIFTY",
                role="BN Alpha",
                config_rel="config/rungs/bn_alpha.yaml",
                tape_rel="reports/bn_trades_f6o3_sm400_mce2_2l.json",
                selection="primary",
            )
            row = load_paper_variant(root, pack)
        self.assertEqual(row["metrics_source"], "yaml_snapshot")
        self.assertTrue(row["tape_stale"])
        self.assertEqual(row["metrics"]["n_trades"], 481)
        self.assertEqual(row["chart"]["count"], 0)

    def test_stale_tape_peak_dd_uses_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config" / "rungs"
            cfg.mkdir(parents=True)
            (cfg / "nifty_alpha.yaml").write_text(NIFTY_YAML, encoding="utf-8")
            tape = root / "reports"
            tape.mkdir()
            (tape / "nifty_trades_tier2_recommended_2l.json").write_text(
                json.dumps(
                    {
                        "investor": {
                            "return_pct": 256.49,
                            "peak_dd_pct": 53.0,
                            "net_pnl": 512983,
                            "n_trades": 241,
                        },
                        "months": [{"ym": "2021-07", "net_pnl": 1, "equity_after": 200001}],
                        "summary": {"start_equity": 200000, "end_equity": 712983},
                    }
                ),
                encoding="utf-8",
            )
            pack = PackDef(
                pack_id="nifty_tier2_recommended",
                underlying="NIFTY",
                role="Nifty Alpha",
                config_rel="config/rungs/nifty_alpha.yaml",
                tape_rel="reports/nifty_trades_tier2_recommended_2l.json",
                selection="primary",
            )
            row = load_paper_variant(root, pack)
        self.assertTrue(row["tape_stale"])
        self.assertEqual(row["metrics_source"], "yaml_snapshot")
        self.assertAlmostEqual(row["metrics"]["peak_dd_pct"], 23.27, places=2)
        self.assertEqual(row["chart"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
