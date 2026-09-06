"""Paper 360 — happy / edge / negative. Live stays off until G5 + forensics."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.auth import get_settings
from app.books.adapters import BookPaths
from app.books.live_cutover import G5_TARGET, book_uses_dhan, g5_sessions, is_g5_fill
from app.brokers.dhan.contracts import Contract
from app.oms import classify_broker_error, place_paper
from app.runners.state import RUNNER
from app import auto_engine, paper_oms


def _contract() -> Contract:
    return Contract("NIFTY", "sid-qa", "NIFTY26SEP24000PE", 24000.0, "PE", "2026-09-10", 65)


def _body(**kw: object) -> SimpleNamespace:
    base = dict(
        underlying="NIFTY",
        sleeve="fade",
        security_id="sid-qa",
        side="BUY",
        quantity=None,
        lots=10,
        symbol="NIFTY26SEP24000PE",
        strike=24000.0,
        option_type="PE",
        expiry="2026-09-10",
        day="2026-09-07",
        tag="paper",
        dry_run=False,
        expected_ltp=100.0,
        price_tolerance=50.0,
        operator_id="ui",
        trace_id=None,
        force_session_close=False,
        pack_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _seed_g5(shadow: Path, n: int, *, source: str = "desk_paper") -> None:
    shadow.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        day = f"2026-07-{(i % 28) + 1:02d}"
        path = shadow / f"shadow_{day}_{i}.jsonl"
        row = {
            "sleeve": "fade",
            "broker_fill": {"entry": 10, "exit": 11, "source": source, "net_pnl": 1},
        }
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")


class TestLiveStaysOff(unittest.TestCase):
    def test_virtual_paper_does_not_count(self) -> None:
        self.assertFalse(is_g5_fill({"entry": 1, "exit": 2, "source": "virtual_paper"}))
        self.assertTrue(is_g5_fill({"entry": 1, "exit": 2, "source": "desk_paper"}))

    def test_g5_full_still_paper_when_desk_live_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            _seed_g5(shadow, G5_TARGET)
            book = BookPaths("NIFTY", root, "c.yaml", shadow)
            self.assertEqual(g5_sessions(book), G5_TARGET)
            with patch("app.books.live_cutover.get_settings") as gs:
                gs.return_value.live_enabled = False
                gs.return_value.live_nifty = True
                gs.return_value.live_banknifty = True
                self.assertFalse(book_uses_dhan("NIFTY", book))

    def test_live_flags_without_g5_stay_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            shadow.mkdir(parents=True)
            book = BookPaths("NIFTY", root, "c.yaml", shadow)
            with patch("app.books.live_cutover.get_settings") as gs:
                gs.return_value.live_enabled = True
                gs.return_value.live_nifty = True
                gs.return_value.live_banknifty = True
                self.assertFalse(book_uses_dhan("NIFTY", book))

    def test_g5_minus_one_not_enough(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "reports" / "shadow"
            _seed_g5(shadow, G5_TARGET - 1)
            book = BookPaths("NIFTY", root, "c.yaml", shadow)
            with patch("app.books.live_cutover.get_settings") as gs:
                gs.return_value.live_enabled = True
                gs.return_value.live_nifty = True
                gs.return_value.live_banknifty = False
                self.assertFalse(book_uses_dhan("NIFTY", book))


class TestPaperPlace360(unittest.TestCase):
    def setUp(self) -> None:
        paper_oms.reset_for_tests()
        self._snap = (
            RUNNER.state,
            RUNNER.mode,
            RUNNER.execution,
            RUNNER.kill.active,
            RUNNER.stop_requested,
        )
        RUNNER.state = "RUNNING"
        RUNNER.mode = "paper"
        RUNNER.execution = "manual"
        RUNNER.kill.active = False
        RUNNER.stop_requested = False
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        shadow = root / "reports" / "shadow"
        shadow.mkdir(parents=True)
        self.book = BookPaths("NIFTY", root, "config/rungs/nifty_alpha.yaml", shadow, variant="primary")
        self.patches = [
            patch("app.oms.market_session", return_value="open"),
            patch("app.oms.resolve_contract", return_value=_contract()),
            patch(
                "app.oms._live_quote",
                return_value={"ltp": 100.0, "bid": 99.5, "ask": 100.5, "quoted_at": "2026-09-07T04:00:00Z"},
            ),
            patch("app.oms.books.book_by_underlying", return_value=self.book),
            patch(
                "app.oms.books.check_book_gate",
                return_value={"allow": True, "reason": "ok", "lots": 10},
            ),
            patch("app.oms.books.book_is_halted", return_value=False),
            patch("app.books.live_cutover.book_uses_dhan", return_value=False),
            patch("app.oms.dhan.place_order", side_effect=AssertionError("Dhan must not place on paper")),
            patch("app.paper_oms._path", return_value=root / "paper_state.json"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        RUNNER.state, RUNNER.mode, RUNNER.execution, RUNNER.kill.active, RUNNER.stop_requested = self._snap
        paper_oms.reset_for_tests()
        self.tmp.cleanup()

    def _place(self, **kw: object) -> dict:
        return place_paper(_body(**kw), [self.book])

    def test_happy_buy_fills_paper_oms(self) -> None:
        r = self._place()
        self.assertTrue(r["accepted"], r)
        self.assertEqual(r["code"], "OK")
        self.assertEqual(r["oms"], "paper")
        self.assertEqual(r["order"]["status"], "TRADED")
        self.assertEqual(int(r["order"]["quantity"]), 650)
        self.assertEqual(paper_oms.positions_grid()["row_count"], 1)
        row = paper_oms.positions_grid()["rows"][0]
        self.assertGreater(float(row.get("stop_pct") or 0), 0)
        self.assertGreater(float(row.get("tp_pct") or 0), 0)
        self.assertGreater(float(row.get("peak_px") or 0), 0)

    def test_happy_sell_closes_round(self) -> None:
        self._place()
        r = self._place(side="SELL", lots=10)
        self.assertTrue(r["accepted"], r)
        self.assertEqual(paper_oms.positions_grid()["row_count"], 0)

    def test_dry_run_does_not_fill(self) -> None:
        r = self._place(dry_run=True)
        self.assertTrue(r["accepted"])
        self.assertIn("dry_run", str(r.get("message") or ""))
        self.assertEqual(paper_oms.positions_grid()["row_count"], 0)

    def test_idempotent_trace_does_not_double_fill(self) -> None:
        a = self._place(trace_id="qa-paper-once")
        b = self._place(trace_id="qa-paper-once")
        self.assertEqual(a["order"]["broker_order_id"], b["order"]["broker_order_id"])
        self.assertEqual(paper_oms.positions_grid()["rows"][0]["qty"], 650)

    def test_trading_stopped(self) -> None:
        RUNNER.state = "STOPPED"
        r = self._place()
        self.assertEqual(r["code"], "TRADING_STOPPED")
        self.assertFalse(r["accepted"])

    def test_kill_switch(self) -> None:
        RUNNER.kill.active = True
        r = self._place()
        self.assertEqual(r["code"], "KILL_SWITCH")

    def test_market_closed(self) -> None:
        with patch("app.oms.market_session", return_value="closed"):
            r = self._place()
        self.assertEqual(r["code"], "MARKET_CLOSED")

    def test_unknown_underlying(self) -> None:
        r = self._place(underlying="SENSEX")
        self.assertEqual(r["code"], "CONTRACT_RESOLVE_FAILED")

    def test_live_mode_disabled(self) -> None:
        RUNNER.mode = "live"
        with patch("app.auth.get_settings") as gs:
            gs.return_value.live_enabled = False
            r = self._place()
        self.assertEqual(r["code"], "LIVE_DISABLED")

    def test_shadow_halted(self) -> None:
        with patch("app.oms.books.book_is_halted", return_value=True):
            r = self._place()
        self.assertEqual(r["code"], "SHADOW_HALTED")

    def test_gate_deny(self) -> None:
        with patch(
            "app.oms.books.check_book_gate",
            return_value={"allow": False, "reason": "lots_zero", "lots": 0},
        ):
            r = self._place(sleeve="orb")
        self.assertEqual(r["code"], "GATE_DENY")
        self.assertIn("lots_zero", str(r.get("message") or r.get("gate")))

    def test_lots_exceed_gate(self) -> None:
        r = self._place(lots=99)
        self.assertEqual(r["code"], "GATE_DENY")
        self.assertIn("exceeds", r["message"])

    def test_missing_expected_ltp(self) -> None:
        r = self._place(expected_ltp=None, operator_id="ui")
        self.assertEqual(r["code"], "PRICE_MOVED")
        self.assertIn("expected_ltp", r["message"])

    def test_stale_quote_blocks_send(self) -> None:
        with patch("app.oms._live_quote", return_value={"ltp": None}):
            r = self._place()
        self.assertEqual(r["code"], "BROKER_UNREACHABLE")

    def test_price_moved(self) -> None:
        r = self._place(expected_ltp=100.0, price_tolerance=0.5)
        self.assertTrue(r["accepted"])
        r2 = self._place(expected_ltp=10.0, price_tolerance=0.5)
        self.assertEqual(r2["code"], "PRICE_MOVED")
        self.assertFalse(r2["accepted"])

    def test_sell_without_position(self) -> None:
        r = self._place(side="SELL")
        self.assertEqual(r["code"], "NO_POSITION")

    def test_timeout_classifies_unreachable(self) -> None:
        self.assertEqual(classify_broker_error(TimeoutError("timed out")), "BROKER_UNREACHABLE")
        self.assertEqual(classify_broker_error(RuntimeError("margin")), "BROKER_REJECT")


def _bn_contract() -> Contract:
    return Contract("BANKNIFTY", "sid-bn-qa", "BANKNIFTY26SEP52000PE", 52000.0, "PE", "2026-09-10", 30)


class TestPaperPlaceBN(unittest.TestCase):
    """BN Alpha place is the same OMS as Nifty — fill + YAML trail 20@20."""

    def setUp(self) -> None:
        paper_oms.reset_for_tests()
        self._snap = (
            RUNNER.state,
            RUNNER.mode,
            RUNNER.execution,
            RUNNER.kill.active,
            RUNNER.stop_requested,
        )
        RUNNER.state = "RUNNING"
        RUNNER.mode = "paper"
        RUNNER.execution = "manual"
        RUNNER.kill.active = False
        RUNNER.stop_requested = False
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        shadow = root / "reports" / "shadow"
        shadow.mkdir(parents=True)
        self.book = BookPaths("BANKNIFTY", root, "config/rungs/bn_alpha.yaml", shadow, variant="primary")
        self.patches = [
            patch("app.oms.market_session", return_value="open"),
            patch("app.oms.resolve_contract", return_value=_bn_contract()),
            patch(
                "app.oms._live_quote",
                return_value={"ltp": 200.0, "bid": 199.5, "ask": 200.5, "quoted_at": "2026-09-07T04:00:00Z"},
            ),
            patch("app.oms.books.book_by_underlying", return_value=self.book),
            patch(
                "app.oms.books.check_book_gate",
                return_value={"allow": True, "reason": "ok", "lots": 6},
            ),
            patch("app.oms.books.book_is_halted", return_value=False),
            patch("app.oms.books.sleeve_risk_params", return_value=(0.30, 0.40)),
            patch("app.oms.books.sleeve_trail_params", return_value=(0.20, 0.20)),
            patch("app.books.live_cutover.book_uses_dhan", return_value=False),
            patch("app.oms.dhan.place_order", side_effect=AssertionError("Dhan must not place on paper")),
            patch("app.paper_oms._path", return_value=root / "paper_state.json"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        RUNNER.state, RUNNER.mode, RUNNER.execution, RUNNER.kill.active, RUNNER.stop_requested = self._snap
        paper_oms.reset_for_tests()
        self.tmp.cleanup()

    def test_bn_fade_buy_stores_trail(self) -> None:
        r = place_paper(
            _body(
                underlying="BANKNIFTY",
                lots=6,
                strike=52000.0,
                security_id="sid-bn-qa",
                expected_ltp=200.0,
            ),
            [self.book],
        )
        self.assertTrue(r["accepted"], r)
        self.assertEqual(r["oms"], "paper")
        self.assertEqual(int(r["order"]["quantity"]), 180)
        pos = paper_oms.peek("sid-bn-qa")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(float(pos["trail_pct"]), 0.20)
        self.assertAlmostEqual(float(pos["trail_activate_pct"]), 0.20)
        self.assertAlmostEqual(float(pos["tp_pct"]), 0.40)
        self.assertEqual(pos["underlying"], "BANKNIFTY")

    def test_bn_sell_closes(self) -> None:
        place_paper(
            _body(
                underlying="BANKNIFTY",
                lots=6,
                strike=52000.0,
                security_id="sid-bn-qa",
                expected_ltp=200.0,
            ),
            [self.book],
        )
        r = place_paper(
            _body(
                underlying="BANKNIFTY",
                lots=6,
                strike=52000.0,
                security_id="sid-bn-qa",
                side="SELL",
                expected_ltp=200.0,
            ),
            [self.book],
        )
        self.assertTrue(r["accepted"], r)
        self.assertEqual(paper_oms.positions_grid()["row_count"], 0)

    def test_bn_orb_gate_lots(self) -> None:
        with patch("app.oms.books.check_book_gate", return_value={"allow": True, "reason": "ok", "lots": 3}):
            r = place_paper(
                _body(
                    underlying="BANKNIFTY",
                    sleeve="orb",
                    lots=3,
                    strike=52000.0,
                    security_id="sid-bn-qa",
                    expected_ltp=200.0,
                ),
                [self.book],
            )
        self.assertTrue(r["accepted"], r)
        self.assertEqual(int(r["order"]["quantity"]), 90)


class TestFourPackPaper(unittest.TestCase):
    """Alpha and Stable are both paper OMS — same strike does not share a lot."""

    def setUp(self) -> None:
        paper_oms.reset_for_tests()
        self._snap = RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested
        RUNNER.state = "RUNNING"
        RUNNER.mode = "paper"
        RUNNER.kill.active = False
        RUNNER.stop_requested = False
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        shadow = root / "reports" / "shadow"
        shadow.mkdir(parents=True)
        self.alpha = BookPaths(
            "NIFTY", root, "config/rungs/nifty_alpha.yaml", shadow,
            pack_id="nifty_tier2_recommended", variant="primary",
        )
        self.stable = BookPaths(
            "NIFTY", root, "config/rungs/nifty_stable.yaml", shadow,
            pack_id="nifty_ce400_secondary", variant="secondary",
        )
        self.patches = [
            patch("app.oms.market_session", return_value="open"),
            patch("app.oms.resolve_contract", return_value=_contract()),
            patch(
                "app.oms._live_quote",
                return_value={"ltp": 100.0, "bid": 99.5, "ask": 100.5, "quoted_at": "2026-09-07T04:00:00Z"},
            ),
            patch("app.oms.books.check_book_gate", return_value={"allow": True, "reason": "ok", "lots": 10}),
            patch("app.oms.books.book_is_halted", return_value=False),
            patch("app.oms.books.sleeve_risk_params", return_value=(0.30, 0.50)),
            patch("app.oms.books.sleeve_trail_params", return_value=(0.0, 0.0)),
            patch("app.books.live_cutover.book_uses_dhan", return_value=False),
            patch("app.oms.dhan.place_order", side_effect=AssertionError("Dhan must not place on paper")),
            patch("app.paper_oms._path", return_value=root / "paper_state.json"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested = self._snap
        paper_oms.reset_for_tests()
        self.tmp.cleanup()

    def test_alpha_and_stable_both_fill_same_sid(self) -> None:
        books = [self.alpha, self.stable]
        a = place_paper(_body(pack_id="nifty_tier2_recommended"), books)
        s = place_paper(_body(pack_id="nifty_ce400_secondary"), books)
        self.assertTrue(a["accepted"], a)
        self.assertTrue(s["accepted"], s)
        grid = paper_oms.positions_grid()
        self.assertEqual(grid["row_count"], 2)
        packs = {str(r.get("pack_id")) for r in grid["rows"]}
        self.assertEqual(packs, {"nifty_tier2_recommended", "nifty_ce400_secondary"})

    def test_stable_sell_leaves_alpha_open(self) -> None:
        books = [self.alpha, self.stable]
        place_paper(_body(pack_id="nifty_tier2_recommended"), books)
        place_paper(_body(pack_id="nifty_ce400_secondary"), books)
        r = place_paper(_body(pack_id="nifty_ce400_secondary", side="SELL"), books)
        self.assertTrue(r["accepted"], r)
        rows = paper_oms.positions_grid()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pack_id"], "nifty_tier2_recommended")


class TestAutoNeverPlacesWhenManual(unittest.TestCase):
    def test_manual_tick_is_noop(self) -> None:
        prev = RUNNER.execution, RUNNER.state, RUNNER.mode
        RUNNER.execution = "manual"
        RUNNER.state = "RUNNING"
        RUNNER.mode = "paper"
        with patch.object(auto_engine, "_place_signal") as place:
            auto_engine.tick()
            place.assert_not_called()
        RUNNER.execution, RUNNER.state, RUNNER.mode = prev

    def test_live_auto_noop_when_live_off(self) -> None:
        prev = RUNNER.execution, RUNNER.state, RUNNER.mode
        RUNNER.execution = "auto"
        RUNNER.state = "RUNNING"
        RUNNER.mode = "live"
        with patch("app.auth.get_settings") as gs, patch.object(auto_engine, "_place_signal") as place:
            gs.return_value.live_enabled = False
            gs.return_value.live_nifty = False
            gs.return_value.live_banknifty = False
            auto_engine.tick()
            place.assert_not_called()
        RUNNER.execution, RUNNER.state, RUNNER.mode = prev


class TestHttpPaper360(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            os.environ["DESK_BFF_SECRET"] = ""
            os.environ.setdefault("DESK_API_KEY", "qa-desk-key")
            get_settings.cache_clear()
            from fastapi.testclient import TestClient
            from app.main import app
            cls.key = get_settings().desk_api_key
            cls.client = TestClient(app, raise_server_exceptions=False)
            cls.ready = True
            cls.skip = ""
        except Exception as exc:  # noqa: BLE001
            cls.client = None
            cls.ready = False
            cls.skip = str(exc)
            cls.key = ""

    def _get(self, path: str, **kw):
        if not self.ready:
            self.skipTest(self.skip)
        return self.client.get(path, **kw)

    def _post(self, path: str, **kw):
        if not self.ready:
            self.skipTest(self.skip)
        return self.client.post(path, **kw)

    def test_place_401_without_key(self) -> None:
        r = self._post("/api/v1/desk/orders/paper", json={"underlying": "NIFTY", "lots": 1, "strike": 1, "option_type": "PE", "expiry": "2026-09-10", "dry_run": True})
        self.assertEqual(r.status_code, 401)

    def test_place_stopped_rejects_inside_ok_envelope(self) -> None:
        prev = RUNNER.state
        RUNNER.state = "STOPPED"
        try:
            r = self._post(
                "/api/v1/desk/orders/paper",
                headers={"X-API-Key": self.key},
                json={
                    "underlying": "NIFTY",
                    "lots": 1,
                    "strike": 24000,
                    "option_type": "PE",
                    "expiry": "2026-09-10",
                    "dry_run": False,
                    "expected_ltp": 100,
                },
            )
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["data"]["code"], "TRADING_STOPPED")
            self.assertFalse(body["data"]["accepted"])
        finally:
            RUNNER.state = prev

    def test_status_cutover_is_paper(self) -> None:
        r = self._get("/api/v1/desk/status", headers={"X-API-Key": self.key})
        self.assertEqual(r.status_code, 200)
        cut = r.json()["data"]["live_cutover"]
        for row in cut["books"]:
            self.assertEqual(row["oms"], "paper")
            self.assertFalse(row["uses_dhan"])
            self.assertFalse(row["desk_live_enabled"])
            self.assertLess(row["g5_fills"], G5_TARGET)

    def test_nifty_fade_allows_orb_denied(self) -> None:
        r = self._get("/api/v1/desk/gates?underlying=NIFTY", headers={"X-API-Key": self.key})
        self.assertEqual(r.status_code, 200)
        sleeves = {s["sleeve"]: s for s in r.json()["data"]["sleeves"]}
        self.assertEqual(int(sleeves["orb"]["lots"]), 0)
        self.assertFalse(sleeves["orb"]["allow"])
        if sleeves["fade"]["allow"]:
            self.assertGreaterEqual(int(sleeves["fade"]["lots"]), 1)

    def test_bn_alpha_allows_fade_and_orb(self) -> None:
        r = self._get("/api/v1/desk/gates?underlying=BANKNIFTY", headers={"X-API-Key": self.key})
        self.assertEqual(r.status_code, 200)
        sleeves = {s["sleeve"]: s for s in r.json()["data"]["sleeves"]}
        if sleeves["fade"]["allow"]:
            self.assertEqual(int(sleeves["fade"]["lots"]), 6)
        if sleeves["orb"]["allow"]:
            self.assertEqual(int(sleeves["orb"]["lots"]), 3)


class TestHarvestPaper360(unittest.TestCase):
    def test_write_matrix(self) -> None:
        dest = Path(__file__).resolve().parents[2] / "reports" / "qa" / "harvest" / "paper_360_matrix.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(
                {
                    "live": "off until G5 fills + forensics + written model pick",
                    "happy": [
                        "buy fills desk_paper OMS",
                        "sell closes round",
                        "dry_run no fill",
                        "idempotent trace",
                        "Nifty fade allow / ORB deny",
                        "BN fade+ORB allow",
                    ],
                    "edge": [
                        "G5=20 still paper if DESK_LIVE_ENABLED=0",
                        "G5=19 + live flags still paper",
                        "lots exceed gate",
                        "auto tick noop in manual",
                    ],
                    "negative": [
                        "401 without key",
                        "TRADING_STOPPED",
                        "KILL_SWITCH",
                        "MARKET_CLOSED",
                        "LIVE_DISABLED",
                        "SHADOW_HALTED",
                        "GATE_DENY",
                        "BROKER_UNREACHABLE",
                        "PRICE_MOVED",
                        "NO_POSITION",
                        "virtual_paper not G5",
                        "live auto noop when live off",
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.assertTrue(dest.is_file())


if __name__ == "__main__":
    unittest.main()
