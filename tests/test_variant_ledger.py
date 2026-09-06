"""Variant ledger: locked tape maps to blotter shape; unknown pack is empty."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.research.stable import PackDef, variant_label
from app.research.variant_ledger import _locked_peak_dd, _month_end_dd, _normalize_locked, to_csv, variant_trades


class TestVariantLedger(unittest.TestCase):
    def test_label(self) -> None:
        pack = PackDef(
            pack_id="nifty_tier2_recommended",
            underlying="NIFTY",
            role="PRIMARY",
            config_rel="x.yaml",
            tape_rel="",
            selection="primary",
        )
        self.assertEqual(variant_label(pack), "Nifty Alpha")

    def test_normalize_locked_loss(self) -> None:
        pack = PackDef(
            pack_id="nifty_tier2_recommended",
            underlying="NIFTY",
            role="PRIMARY",
            config_rel="x.yaml",
            tape_rel="",
            selection="primary",
        )
        row = _normalize_locked(
            {
                "day": "2021-07-22",
                "sleeve": "fade",
                "side": "PE",
                "symbol": "NIFTY2172215750PE",
                "lots": 10,
                "qty": 750,
                "entry": 29.6,
                "exit": 19.2,
                "exit_reason": "stop",
                "costs_inr": 509.53,
                "net_pnl": -8305.22,
            },
            pack,
            0,
        )
        self.assertEqual(row["underlying"], "NIFTY")
        self.assertEqual(row["mode"], "locked")
        self.assertEqual(row["option_type"], "PE")
        self.assertEqual(row["side"], "BUY")
        self.assertEqual(row["lot_size"], 75)
        self.assertEqual(row["net_pnl"], -8305.22)

    def test_unknown_pack(self) -> None:
        payload = variant_trades(pack_id="nope", source="locked")
        self.assertEqual(payload["error"], "unknown_pack")
        self.assertEqual(payload["trades"], [])

    def test_csv_header(self) -> None:
        text = to_csv([{"day": "2021-07-22", "net_pnl": -1, "symbol": "X", "underlying": "NIFTY"}])
        self.assertTrue(text.startswith("day,symbol,"))
        self.assertIn("NIFTY", text)

    def test_locked_from_temp_tape(self) -> None:
        pack = PackDef(
            pack_id="nifty_tier2_recommended",
            underlying="NIFTY",
            role="PRIMARY",
            config_rel="c.yaml",
            tape_rel="reports/t.json",
            selection="primary",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            (reports / "t.json").write_text(
                json.dumps(
                    {
                        "investor": {"return_pct": 1, "peak_dd_pct": 2, "net_pnl": 3, "n_trades": 1},
                        "months": [],
                        "trades": [
                            {
                                "day": "2021-08-02",
                                "sleeve": "fade",
                                "side": "CE",
                                "symbol": "NIFTY1",
                                "lots": 1,
                                "qty": 65,
                                "entry": 10,
                                "exit": 12,
                                "exit_reason": "tp",
                                "net_pnl": 100,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch("app.research.variant_ledger.paper_pack", return_value=pack):
                with patch("app.research.variant_ledger._roots", return_value=(root, root)):
                    payload = variant_trades(pack_id="nifty_tier2_recommended", source="locked")
        self.assertEqual(payload["trade_count"], 1)
        self.assertEqual(payload["trades"][0]["net_pnl"], 100)
        self.assertEqual(payload["label"], "Nifty Alpha")

    def test_month_end_dd_matches_locked_capital_pct(self) -> None:
        months = [
            {"ym": "2021-07", "net_pnl": -46540},
            {"ym": "2021-08", "net_pnl": 100000},
        ]
        dd_inr, pct = _month_end_dd(months, 200_000.0, date(2021, 7, 1), date(2021, 8, 31))
        self.assertEqual(dd_inr, 46540.0)
        self.assertEqual(pct, 23.27)

    def test_locked_peak_uses_investor_when_window_covers_tape(self) -> None:
        months = [{"ym": "2021-07", "net_pnl": -10}, {"ym": "2026-06", "net_pnl": 10}]
        dd_inr, pct = _locked_peak_dd(
            {"peak_dd_pct": 23.27},
            months,
            200_000.0,
            date(2021, 7, 1),
            date(2026, 6, 30),
        )
        self.assertEqual(pct, 23.27)
        self.assertEqual(dd_inr, 46540.0)
