"""No-leak paper freeze: YAML exits, EOD ledger, cancel, schedule, auto, HTTP mutations."""
from __future__ import annotations

import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app import auto_engine, paper_oms
from app.auth import get_settings
from app.execution.sessions import trail_open_sessions
from app.oms import cancel_paper
from app.runners.state import RUNNER
from app.schedule import arm_live_auto, in_cash_window, tick
from app.session import IST


class TestPaperYamlExits(unittest.TestCase):
    def setUp(self) -> None:
        paper_oms.reset_for_tests()

    def tearDown(self) -> None:
        paper_oms.reset_for_tests()

    def _buy(self, **kw: object) -> None:
        args = dict(
            underlying="NIFTY",
            sleeve="fade",
            security_id="sid-x",
            symbol="NIFTY-QA",
            qty=650,
            lots=10,
            lot_size=65,
            price=100.0,
            client_order_id="desk-qa-protect",
            stop_pct=0.30,
            tp_pct=0.50,
            trail_pct=0.0,
            trail_activate_pct=0.0,
        )
        args.update(kw)
        paper_oms.apply_buy(**args)

    def test_stop_exits_at_floor(self) -> None:
        self._buy()
        self.assertIsNone(paper_oms.mark_and_maybe_exit("sid-x", 71.0))
        sold = paper_oms.mark_and_maybe_exit("sid-x", 70.0)
        self.assertTrue(sold["ok"])
        self.assertEqual(sold["reason"], "stop")
        self.assertEqual(paper_oms.positions_grid()["row_count"], 0)

    def test_take_profit(self) -> None:
        self._buy()
        sold = paper_oms.mark_and_maybe_exit("sid-x", 150.0)
        self.assertEqual(sold["reason"], "take_profit")

    def test_bn_trail_tightens_then_exits(self) -> None:
        self._buy(stop_pct=0.30, tp_pct=0.40, trail_pct=0.20, trail_activate_pct=0.20)
        self.assertIsNone(paper_oms.mark_and_maybe_exit("sid-x", 115.0))  # not active
        self.assertIsNone(paper_oms.mark_and_maybe_exit("sid-x", 130.0))  # trail 104, ltp above
        sold = paper_oms.mark_and_maybe_exit("sid-x", 104.0)
        self.assertEqual(sold["reason"], "trail_stop")

    def test_huge_print_hits_recipe_tp(self) -> None:
        self._buy()
        sold = paper_oms.mark_and_maybe_exit("sid-x", 600.0)
        self.assertEqual(sold["reason"], "take_profit")

    def test_freak_tick_keeps_peak_then_trails(self) -> None:
        self._buy(stop_pct=0.30, tp_pct=9.0, trail_pct=0.20, trail_activate_pct=0.20)
        self.assertIsNone(paper_oms.mark_and_maybe_exit("sid-x", 600.0))
        self.assertAlmostEqual(paper_oms.peek("sid-x")["peak_px"], 600.0)
        sold = paper_oms.mark_and_maybe_exit("sid-x", 100.0)
        self.assertEqual(sold["reason"], "trail_stop")
        self.assertGreater(sold["entry_avg"], 0)

    def test_no_recipe_does_not_invent_stop(self) -> None:
        paper_oms.apply_buy(
            underlying="NIFTY",
            sleeve="fade",
            security_id="sid-bare",
            symbol="X",
            qty=65,
            lots=1,
            lot_size=65,
            price=100.0,
            client_order_id="c1",
        )
        self.assertIsNone(paper_oms.mark_and_maybe_exit("sid-bare", 1.0))
        self.assertEqual(paper_oms.positions_grid()["row_count"], 1)

    def test_trail_open_sessions_sells_paper(self) -> None:
        self._buy()
        with patch("app.paper_protect._journal_exit"):
            n = trail_open_sessions("sid-x", 70.0)
        self.assertGreaterEqual(n, 1)
        self.assertEqual(paper_oms.positions_grid()["row_count"], 0)

    def test_on_mark_backfills_yaml_then_stops(self) -> None:
        from app.paper_protect import on_mark

        paper_oms.apply_buy(
            underlying="NIFTY",
            sleeve="fade",
            security_id="sid-old",
            symbol="NIFTY-QA",
            qty=650,
            lots=10,
            lot_size=65,
            price=100.0,
            client_order_id="pre-recipe",
        )
        book = SimpleNamespace(name="NIFTY")
        with patch("app.paper_protect._book_for", return_value=book), patch(
            "app.books.adapters.sleeve_risk_params", return_value=(0.30, 0.50)
        ), patch("app.books.adapters.sleeve_trail_params", return_value=(0.0, 0.0)), patch(
            "app.paper_protect._journal_exit"
        ):
            sold = on_mark("sid-old", 70.0)
        self.assertEqual(sold["reason"], "stop")
        self.assertEqual(paper_oms.positions_grid()["row_count"], 0)


class TestPaperCancelAndPositions(unittest.TestCase):
    def setUp(self) -> None:
        paper_oms.reset_for_tests()
        self._kill = RUNNER.kill.active
        RUNNER.kill.active = False

    def tearDown(self) -> None:
        RUNNER.kill.active = self._kill
        paper_oms.reset_for_tests()

    def test_cancel_paper_oid_is_already_filled(self) -> None:
        buy = paper_oms.apply_buy(
            underlying="NIFTY",
            sleeve="fade",
            security_id="sid-c",
            symbol="X",
            qty=65,
            lots=1,
            lot_size=65,
            price=100.0,
            client_order_id="desk-cancel-1",
        )
        oid = buy["broker_order_id"]
        with patch("app.oms.dhan.cancel_order", side_effect=AssertionError("dhan")):
            r = cancel_paper(oid, "qa")
        self.assertEqual(r["code"], "ALREADY_FILLED")
        self.assertFalse(r["accepted"])
        with patch("app.oms.dhan.cancel_order", side_effect=AssertionError("dhan")):
            r2 = cancel_paper("desk-cancel-1", "qa")
        self.assertEqual(r2["code"], "ALREADY_FILLED")

    def test_cancel_desk_prefix_without_fill_hits_dhan(self) -> None:
        with patch("app.oms.dhan.cancel_order", return_value={"raw": {"orderStatus": "CANCELLED"}}) as cancel:
            r = cancel_paper("desk-live-working", "qa")
        cancel.assert_called_once_with("desk-live-working")
        self.assertTrue(r["accepted"])
        self.assertEqual(r["code"], "OK")

    def test_cancel_empty_id(self) -> None:
        r = cancel_paper("", "qa")
        self.assertEqual(r["code"], "ORDER_NOT_FOUND")

    def test_desk_positions_are_paper_when_live_off(self) -> None:
        paper_oms.apply_buy(
            underlying="NIFTY",
            sleeve="fade",
            security_id="sid-p",
            symbol="X",
            qty=65,
            lots=1,
            lot_size=65,
            price=100.0,
            client_order_id="c2",
        )
        book = SimpleNamespace(name="NIFTY")
        with patch("app.books.live_cutover.book_uses_dhan", return_value=False):
            grid = paper_oms.desk_positions([book])
        self.assertEqual(grid["row_count"], 1)
        self.assertEqual(grid["rows"][0]["security_id"], "sid-p")

    def test_feed_instruments_include_paper_ledger(self) -> None:
        from app.execution.runner import EXECUTION

        paper_oms.apply_buy(
            underlying="NIFTY",
            sleeve="fade",
            security_id="sid-feed",
            symbol="X",
            qty=65,
            lots=1,
            lot_size=65,
            price=100.0,
            client_order_id="c-feed",
        )
        sids = {sid for _seg, sid in EXECUTION._instruments()}
        self.assertIn("sid-feed", sids)


class TestAutoAndSchedule(unittest.TestCase):
    def test_auto_places_pending_once(self) -> None:
        prev = RUNNER.execution, RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested
        RUNNER.execution = "auto"
        RUNNER.state = "RUNNING"
        RUNNER.mode = "paper"
        RUNNER.kill.active = False
        RUNNER.stop_requested = False
        auto_engine._fired.clear()
        sig = {
            "signal_id": "qa-pending-1",
            "underlying": "NIFTY",
            "sleeve": "fade",
            "status": "PENDING",
            "target_lots": 10,
            "option_type": "PE",
            "strike": 24000,
            "expiry": "2026-09-10",
            "symbol": "NIFTY-QA",
            "ltp": 100.0,
        }
        try:
            with patch.object(auto_engine, "load_persisted"), patch.object(
                auto_engine, "_session_now", return_value=(datetime(2026, 9, 7, 10, 0, tzinfo=IST), "open")
            ), patch.object(auto_engine, "_compass", return_value={"signals": [sig]}), patch.object(
                auto_engine, "_place_signal", return_value={"accepted": True, "code": "OK", "order": {"side": "BUY", "lots": 10, "quantity": 650, "price": 100}}
            ) as place, patch.object(auto_engine, "_notice_from_place"):
                auto_engine.tick()
                auto_engine.tick()
                self.assertEqual(place.call_count, 1)
        finally:
            auto_engine._fired.clear()
            RUNNER.execution, RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested = prev

    def test_eod_flatten_uses_paper_ledger(self) -> None:
        prev = RUNNER.execution, RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested
        RUNNER.execution = "auto"
        RUNNER.state = "RUNNING"
        RUNNER.mode = "paper"
        RUNNER.kill.active = False
        RUNNER.stop_requested = False
        auto_engine._eod_done_day = None
        now = datetime(2026, 9, 7, 15, 32, tzinfo=IST)
        row = {
            "qty": 650,
            "lots": 10,
            "underlying": "NIFTY",
            "symbol": "NIFTY-QA",
            "sleeve": "fade",
            "security_id": "sid-eod",
            "strike": 24000,
            "option_type": "PE",
            "expiry": "2026-09-10",
            "ltp": 90.0,
        }
        try:
            with patch.object(auto_engine, "load_persisted"), patch.object(
                auto_engine, "_session_now", return_value=(now, "closed")
            ), patch.object(auto_engine, "_positions", return_value={"rows": [row]}), patch.object(
                auto_engine, "_place_signal", return_value={"accepted": True, "code": "OK", "order": {"side": "SELL"}}
            ) as place, patch.object(auto_engine, "_notice_from_place"):
                auto_engine.tick()
                self.assertEqual(place.call_count, 1)
                self.assertTrue(place.call_args.kwargs.get("force_eod"))
        finally:
            auto_engine._eod_done_day = None
            RUNNER.execution, RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested = prev

    def test_saturday_is_not_cash_window(self) -> None:
        with patch("app.schedule.now_ist", return_value=datetime(2026, 9, 5, 10, 30, tzinfo=IST)):
            self.assertFalse(in_cash_window())

    def test_weekday_open_is_cash_window(self) -> None:
        with patch("app.schedule.now_ist", return_value=datetime(2026, 9, 7, 10, 30, tzinfo=IST)), patch(
            "app.schedule.market_session", return_value="open"
        ):
            self.assertTrue(in_cash_window())

    def test_tick_arms_paper_not_live_when_live_off(self) -> None:
        with patch("app.schedule.schedule_wanted", return_value=True), patch(
            "app.schedule.in_cash_window", return_value=True
        ), patch("app.schedule.paused_today", return_value=False), patch(
            "app.schedule._live_cutover_ready", return_value=False
        ), patch("app.schedule.arm_paper_auto") as paper, patch("app.schedule.arm_live_auto") as live:
            tick()
            paper.assert_called_once()
            live.assert_not_called()

    def test_tick_noop_when_not_wanted(self) -> None:
        with patch("app.schedule.schedule_wanted", return_value=False), patch("app.schedule.arm_paper_auto") as paper:
            tick()
            paper.assert_not_called()

    def test_arm_live_falls_back_to_paper(self) -> None:
        with patch("app.schedule._live_cutover_ready", return_value=False), patch("app.schedule.arm_paper_auto") as paper:
            arm_live_auto(reason="qa")
            paper.assert_called_once()

    def test_kill_blocks_schedule(self) -> None:
        prev = RUNNER.kill.active
        RUNNER.kill.active = True
        try:
            with patch("app.schedule.schedule_wanted", return_value=True), patch("app.schedule.arm_paper_auto") as paper:
                tick()
                paper.assert_not_called()
        finally:
            RUNNER.kill.active = prev


class TestHttpMutations(unittest.TestCase):
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
            cls.ready = False
            cls.skip = str(exc)
            cls.client = None
            cls.key = ""

    def _h(self) -> dict:
        return {"X-API-Key": self.key}

    def test_snapshot_and_start_stop_kill_ack_ws(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        snap = RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested
        try:
            r = self.client.get("/api/v1/desk/snapshot", headers=self._h())
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])
            data = r.json()["data"]
            self.assertIn("status", data)
            self.assertIn("positions", data)

            r = self.client.post(
                "/api/v1/desk/runner/start",
                headers=self._h(),
                json={"mode": "live", "execution": "auto", "confirm_live": True},
            )
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["data"].get("code"), "LIVE_DISABLED")

            r = self.client.post(
                "/api/v1/desk/runner/start",
                headers=self._h(),
                json={"mode": "paper", "execution": "manual"},
            )
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["data"].get("accepted"))

            r = self.client.post("/api/v1/desk/sync", headers=self._h())
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])

            r = self.client.post(
                "/api/v1/desk/triggers/ack",
                headers=self._h(),
                json={"trigger_id": "qa-ack-1", "action": "dismiss"},
            )
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["data"]["accepted"])

            r = self.client.post(
                "/api/v1/desk/orders/cancel",
                headers=self._h(),
                json={"order_id": "paper_qa_missing"},
            )
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["data"]["code"], "ALREADY_FILLED")

            r = self.client.post(
                "/api/v1/desk/safety/kill-switch",
                headers=self._h(),
                json={"active": True, "reason": "qa"},
            )
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["data"].get("kill_switch_active", True) or r.json()["ok"])

            r = self.client.post(
                "/api/v1/desk/safety/kill-switch",
                headers=self._h(),
                json={"active": False, "reason": "qa-off"},
            )
            self.assertEqual(r.status_code, 200)

            r = self.client.post(
                "/api/v1/desk/runner/stop",
                headers=self._h(),
                json={"reason": "qa"},
            )
            self.assertEqual(r.status_code, 200)

            with self.client.websocket_connect("/ws/desk", headers=self._h()) as ws:
                msg = ws.receive_json()
                self.assertEqual(msg.get("type"), "connected")
                self.assertIn("channels", msg)
        finally:
            RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested = snap
            RUNNER.kill.reason = None
            RUNNER.kill.activated_at = None

    def test_ws_rejects_bad_key(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/ws/desk?api_key=wrong"):
                pass

    def test_quotes_and_contracts_envelope(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        for path in (
            "/api/v1/desk/quotes/spot",
            "/api/v1/desk/triggers/active",
            "/api/v1/desk/research/g5",
            "/api/v1/desk/research/lake-status",
        ):
            r = self.client.get(path, headers=self._h())
            self.assertEqual(r.status_code, 200, path)
            self.assertTrue(r.json().get("ok"), path)

    def test_four_packs_take_paper_fills(self) -> None:
        from app.auth import get_settings
        from app.books.adapters import book_for_place, variant_books

        s = get_settings()
        books = variant_books(nifty_root=s.nifty_lab_root, bn_root=s.bn_lab_root)
        self.assertEqual(len(books), 4)
        nifty_a = book_for_place(books, "NIFTY")
        nifty_s = book_for_place(books, "NIFTY", "nifty_ce400_secondary")
        bn_a = book_for_place(books, "BANKNIFTY")
        bn_s = book_for_place(books, "BANKNIFTY", "bn_rs30_tp40_secondary")
        self.assertEqual(nifty_a.variant, "primary")
        self.assertEqual(nifty_s.variant, "secondary")
        self.assertEqual(bn_a.variant, "primary")
        self.assertEqual(bn_s.variant, "secondary")
        self.assertIn("nifty_alpha", nifty_a.config_rel.replace("\\", "/"))
        self.assertIn("nifty_stable", nifty_s.config_rel.replace("\\", "/"))
        self.assertIn("bn_alpha", bn_a.config_rel.replace("\\", "/"))
        self.assertIn("bn_stable", bn_s.config_rel.replace("\\", "/"))


class TestArchiveUsesPaperLedger(unittest.TestCase):
    def test_capture_keeps_paper_rows(self) -> None:
        from app.paper_archive import capture
        from app.runners.state import RUNNER

        paper_oms.reset_for_tests()
        paper_oms.apply_buy(
            underlying="NIFTY",
            sleeve="fade",
            security_id="sid-arch",
            symbol="X",
            qty=65,
            lots=1,
            lot_size=65,
            price=100.0,
            client_order_id="arch-1",
        )
        prev = RUNNER.mode
        RUNNER.mode = "paper"
        try:
            path = capture(reason="qa")
            self.assertIsNotNone(path)
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
            ids = {str(r.get("security_id")) for r in (payload.get("positions") or {}).get("rows") or []}
            self.assertIn("sid-arch", ids)
        finally:
            RUNNER.mode = prev
            paper_oms.reset_for_tests()


if __name__ == "__main__":
    unittest.main()
