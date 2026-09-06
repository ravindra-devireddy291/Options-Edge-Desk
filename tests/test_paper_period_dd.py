"""Paper-period DD is rupees from peak since paper start — not lab lifetime equity."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.books.adapters import BookPaths, paper_period_stats


class TestPaperPeriodDd(unittest.TestCase):
    def test_profit_path_has_zero_drawdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            shadow.mkdir(parents=True)
            cfg = root / "c.yaml"
            cfg.write_text("name: nifty_paper_2l_tier2_recommended\ntotal_capital_inr: 200000\n", encoding="utf-8")
            row = {
                "config": "nifty_paper_2l_tier2_recommended",
                "lab": {"status": "ok", "net_pnl": 16246.45, "exit_reason": "eod"},
                "broker_fill": {"net_pnl": 16246.45, "exit": 139.2, "source": "desk_paper"},
            }
            (shadow / "shadow_2026-08-26.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            book = BookPaths(
                "NIFTY",
                root,
                "c.yaml",
                shadow,
                pack_id="nifty_tier2_recommended",
                variant="primary",
                config_name="nifty_paper_2l_tier2_recommended",
            )
            stats = paper_period_stats(book)
        self.assertEqual(stats["realized_pnl"], 16246.45)
        self.assertEqual(stats["paper_dd_inr"], 0.0)
        self.assertEqual(stats["paper_dd_pct"], 0.0)
        self.assertEqual(stats["equity"], 216246.45)

    def test_secondary_without_fills_is_zero_not_lab_dd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            shadow.mkdir(parents=True)
            cfg = root / "c.yaml"
            cfg.write_text("name: nifty_paper_2l_ce400_secondary\ntotal_capital_inr: 200000\n", encoding="utf-8")
            other = {
                "config": "nifty_paper_2l_tier2_recommended",
                "lab": {"status": "ok", "net_pnl": 16246.45, "exit_reason": "eod"},
                "broker_fill": {"net_pnl": 16246.45, "exit": 1, "source": "desk_paper"},
            }
            (shadow / "shadow_2026-08-26.jsonl").write_text(json.dumps(other) + "\n", encoding="utf-8")
            book = BookPaths(
                "NIFTY",
                root,
                "c.yaml",
                shadow,
                pack_id="nifty_ce400_secondary",
                variant="secondary",
                config_name="nifty_paper_2l_ce400_secondary",
            )
            stats = paper_period_stats(book)
        self.assertEqual(stats["realized_pnl"], 0.0)
        self.assertEqual(stats["trade_count"], 0)
        self.assertEqual(stats["paper_dd_inr"], 0.0)

    def test_circuit_uses_paper_dd_not_lab_lifetime(self) -> None:
        from unittest.mock import patch

        from app.books.adapters import circuit_from_books

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            shadow.mkdir(parents=True)
            (shadow / "execution_state.json").write_text(
                json.dumps({"equity": 216246.45, "peak_equity": 242000.0, "capital": 200000}),
                encoding="utf-8",
            )
            cfg = root / "c.yaml"
            cfg.write_text("name: nifty_paper_2l_tier2_recommended\ntotal_capital_inr: 200000\n", encoding="utf-8")
            row = {
                "config": "nifty_paper_2l_tier2_recommended",
                "lab": {"status": "ok", "net_pnl": 16246.45, "exit_reason": "eod"},
                "broker_fill": {"net_pnl": 16246.45, "exit": 139.2, "source": "desk_paper"},
            }
            (shadow / "shadow_2026-08-26.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            book = BookPaths(
                "NIFTY",
                root,
                "c.yaml",
                shadow,
                pack_id="nifty_tier2_recommended",
                variant="primary",
                config_name="nifty_paper_2l_tier2_recommended",
            )
            with patch(
                "app.books.adapters._circuit_limits",
                return_value={"daily_loss_limit_inr": None, "max_drawdown_from_peak_pct": 0.20},
            ):
                payload = circuit_from_books([book])
        self.assertEqual(payload["peak_dd_pct"], 0.0)
        self.assertEqual(payload["books"][0]["dd_inr"], 0.0)
        self.assertEqual(payload["books"][0]["dd_mode"], "paper")
        self.assertEqual(payload["books"][0]["label"], "NIFTY Alpha")
        self.assertEqual(payload["books"][0]["month_pnl"], 16246.45)
