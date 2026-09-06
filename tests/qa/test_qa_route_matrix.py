"""Every /api/v1 route is probed with a key. Never 500. Dhan HTTP is forbidden."""
from __future__ import annotations

import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app.auth import get_settings
from app.brokers.dhan.contracts import Contract
from app.runners.state import RUNNER


def _nifty() -> Contract:
    return Contract("NIFTY", "sid-qa", "NIFTY26SEP24000PE", 24000.0, "PE", "2026-09-10", 65)


def _bn() -> Contract:
    return Contract("BANKNIFTY", "sid-bn-qa", "BANKNIFTY26SEP52000PE", 52000.0, "PE", "2026-09-10", 30)


FAKE_TOKEN = {
    "api_key": "CLIENT123456",
    "access_token_masked": "abcd••••••••",
    "token_ok": True,
    "has_access_token": True,
    "broker": "dhan",
    "auto": {"ok": True, "raw_keys": ["accessToken"], "accessToken": "LEAK"},
}

CHAIN = {
    "underlying": "NIFTY",
    "spot": 24000.0,
    "lot_size": 65,
    "expiry": "2026-09-10",
    "expiries": ["2026-09-10"],
    "atm_strike": 24000.0,
    "strike_step": 50,
    "strikes": [23950.0, 24000.0, 24050.0],
}

# (method, FastAPI path template, concrete URL, optional JSON body)
PROBES: list[tuple[str, str, str, dict | None]] = [
    ("GET", "/api/v1/desk/status", "/api/v1/desk/status", None),
    ("GET", "/api/v1/desk/snapshot", "/api/v1/desk/snapshot", None),
    ("GET", "/api/v1/desk/research/stable", "/api/v1/desk/research/stable", None),
    ("GET", "/api/v1/desk/research/stable/{underlying}", "/api/v1/desk/research/stable/NIFTY", None),
    ("GET", "/api/v1/desk/research/stable/{underlying}", "/api/v1/desk/research/stable/BANKNIFTY", None),
    ("GET", "/api/v1/desk/research/variant-summary", "/api/v1/desk/research/variant-summary?pack_id=nifty_alpha", None),
    ("GET", "/api/v1/desk/research/variant-trades", "/api/v1/desk/research/variant-trades?pack_id=bn_alpha", None),
    ("GET", "/api/v1/desk/research/lake-status", "/api/v1/desk/research/lake-status", None),
    ("GET", "/api/v1/desk/research/lake-download", "/api/v1/desk/research/lake-download?underlying=NIFTY&kind=spot&from=2026-08-03&to=2026-08-03", None),
    ("GET", "/api/v1/desk/research/g5", "/api/v1/desk/research/g5", None),
    ("GET", "/api/v1/desk/research/oos", "/api/v1/desk/research/oos", None),
    ("GET", "/api/v1/desk/research/cost-honesty", "/api/v1/desk/research/cost-honesty", None),
    ("GET", "/api/v1/desk/research/scale", "/api/v1/desk/research/scale", None),
    ("GET", "/api/v1/desk/research/brief", "/api/v1/desk/research/brief", None),
    ("GET", "/api/v1/desk/health/full", "/api/v1/desk/health/full", None),
    ("GET", "/api/v1/desk/runner", "/api/v1/desk/runner", None),
    ("GET", "/api/v1/desk/positions", "/api/v1/desk/positions", None),
    ("GET", "/api/v1/desk/orders/open", "/api/v1/desk/orders/open", None),
    ("GET", "/api/v1/desk/trades/today", "/api/v1/desk/trades/today", None),
    ("GET", "/api/v1/desk/trades/history", "/api/v1/desk/trades/history?from=2026-09-01&to=2026-09-01", None),
    ("GET", "/api/v1/desk/trades/export", "/api/v1/desk/trades/export?from=2026-09-01&to=2026-09-01", None),
    ("GET", "/api/v1/desk/signals/today", "/api/v1/desk/signals/today", None),
    ("GET", "/api/v1/desk/contracts", "/api/v1/desk/contracts?underlying=NIFTY", None),
    ("GET", "/api/v1/desk/contracts", "/api/v1/desk/contracts?underlying=BANKNIFTY", None),
    ("GET", "/api/v1/desk/quotes/option", "/api/v1/desk/quotes/option", None),
    ("GET", "/api/v1/desk/quotes/option", "/api/v1/desk/quotes/option?security_id=sid-qa&underlying=NIFTY", None),
    ("GET", "/api/v1/desk/quotes/spot", "/api/v1/desk/quotes/spot", None),
    ("GET", "/api/v1/desk/gates", "/api/v1/desk/gates?underlying=NIFTY", None),
    ("GET", "/api/v1/desk/gates", "/api/v1/desk/gates?underlying=BANKNIFTY", None),
    ("GET", "/api/v1/desk/triggers/active", "/api/v1/desk/triggers/active", None),
    ("GET", "/api/v1/desk/orders/queue", "/api/v1/desk/orders/queue", None),
    ("GET", "/api/v1/desk/signals/last-cycle", "/api/v1/desk/signals/last-cycle", None),
    ("GET", "/api/v1/desk/signals/rejected", "/api/v1/desk/signals/rejected", None),
    ("GET", "/api/v1/desk/safety/kill-switch", "/api/v1/desk/safety/kill-switch", None),
    ("GET", "/api/v1/desk/safety/circuit-breaker", "/api/v1/desk/safety/circuit-breaker", None),
    ("GET", "/api/v1/desk/safety/shadow-book", "/api/v1/desk/safety/shadow-book", None),
    ("GET", "/api/v1/desk/system/token", "/api/v1/desk/system/token", None),
    ("GET", "/api/v1/desk/audit/tail", "/api/v1/desk/audit/tail", None),
    ("POST", "/api/v1/desk/research/variant-sync", "/api/v1/desk/research/variant-sync", {"pack_id": "nifty_alpha"}),
    ("POST", "/api/v1/desk/runner/start", "/api/v1/desk/runner/start", {"mode": "paper", "execution": "manual"}),
    ("POST", "/api/v1/desk/runner/stop", "/api/v1/desk/runner/stop", {"reason": "qa-matrix"}),
    ("POST", "/api/v1/desk/triggers/ack", "/api/v1/desk/triggers/ack", {"trigger_id": "qa-matrix", "action": "dismiss"}),
    ("POST", "/api/v1/desk/sync", "/api/v1/desk/sync", None),
    ("POST", "/api/v1/desk/safety/kill-switch", "/api/v1/desk/safety/kill-switch", {"active": False, "reason": "qa-matrix"}),
    ("POST", "/api/v1/desk/system/token", "/api/v1/desk/system/token", {"generate_now": False}),
    ("POST", "/api/v1/desk/system/token/renew", "/api/v1/desk/system/token/renew", None),
    ("POST", "/api/v1/desk/orders/paper", "/api/v1/desk/orders/paper", {
        "underlying": "NIFTY", "lots": 1, "strike": 24000, "option_type": "PE",
        "expiry": "2026-09-10", "dry_run": True,
    }),
    ("POST", "/api/v1/desk/orders/paper", "/api/v1/desk/orders/paper", {
        "underlying": "BANKNIFTY", "lots": 1, "strike": 52000, "option_type": "PE",
        "expiry": "2026-09-10", "dry_run": True,
    }),
    ("POST", "/api/v1/desk/orders/cancel", "/api/v1/desk/orders/cancel", {"order_id": "paper_qa_matrix"}),
    ("POST", "/api/v1/desk/cycle/tick", "/api/v1/desk/cycle/tick", None),
]

MISSING_QUERY = (
    "/api/v1/desk/gates",
    "/api/v1/desk/contracts",
    "/api/v1/desk/trades/history",
    "/api/v1/desk/research/variant-summary",
    "/api/v1/desk/research/lake-download",
)


class TestRouteMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["DESK_BFF_SECRET"] = ""
        os.environ.setdefault("DESK_API_KEY", "qa-desk-key")
        get_settings.cache_clear()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.key = get_settings().desk_api_key
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.app = app

    def _h(self) -> dict:
        return {"X-API-Key": self.key}

    def _dhan_stack(self) -> ExitStack:
        stack = ExitStack()
        dhan_http = AssertionError("Dhan HTTP in QA route matrix")
        stack.enter_context(patch("app.brokers.dhan.client._request", side_effect=dhan_http))
        stack.enter_context(patch("app.brokers.dhan.client.token_status", return_value=FAKE_TOKEN))
        stack.enter_context(patch("app.brokers.dhan.client.spots_with_change", return_value={
            "NIFTY": {"ltp": 24000.0, "change_pct": 0.1, "change_pts": 24.0},
            "BANKNIFTY": {"ltp": 52000.0, "change_pct": -0.1, "change_pts": -52.0},
        }))
        stack.enter_context(patch("app.brokers.dhan.client.spots", return_value={
            "NIFTY": 24000.0, "BANKNIFTY": 52000.0, "nifty_spot": 24000.0, "banknifty_spot": 52000.0,
        }))
        stack.enter_context(patch("app.brokers.dhan.client.broker_reachable", return_value=True))
        stack.enter_context(patch("app.brokers.dhan.client.available_cash", return_value=1_000_000.0))
        stack.enter_context(patch("app.brokers.dhan.client.positions_grid", return_value={"row_count": 0, "rows": []}))
        stack.enter_context(patch("app.brokers.dhan.client.open_orders_response", return_value={"count": 0, "orders": []}))
        stack.enter_context(patch("app.brokers.dhan.client.market_quote_option", return_value={
            "ltp": 100.0, "bid": 99.5, "ask": 100.5, "quoted_at": "2026-09-06T00:00:00Z", "stale": False,
        }))
        stack.enter_context(patch("app.brokers.dhan.client.persist_env_vars"))
        stack.enter_context(patch("app.brokers.dhan.client.set_access_token"))
        stack.enter_context(patch("app.brokers.dhan.client.ensure_fresh_token", return_value={"ok": True, "action": "fresh"}))
        stack.enter_context(patch("app.brokers.dhan.client.generate_access_token_totp", return_value={"ok": True, "action": "generated_totp"}))
        def _chain(*, underlying: str = "NIFTY", **_kw):
            if str(underlying).upper() == "BANKNIFTY":
                return {**CHAIN, "underlying": "BANKNIFTY", "spot": 52000.0, "lot_size": 30, "atm_strike": 52000.0}
            return dict(CHAIN)

        def _resolve(**kw):
            und = str(kw.get("underlying") or "NIFTY").upper()
            return _bn() if und == "BANKNIFTY" else _nifty()

        stack.enter_context(patch("app.main.chain_snapshot", side_effect=lambda **kw: _chain(**kw)))
        stack.enter_context(patch("app.main.resolve_contract", side_effect=lambda **kw: _resolve(**kw)))
        stack.enter_context(patch("app.oms.resolve_contract", side_effect=lambda **kw: _resolve(**kw)))
        stack.enter_context(patch("app.main.research_tape_sync.start_sync", return_value={
            "ok": True, "started": False, "error": "up_to_date", "pack_id": "nifty_alpha",
        }))
        stack.enter_context(patch("app.lake_ingest.export_file", return_value=(
            b"ts,px\n2026-08-03T09:15:00,24000\n",
            "nifty_spot_2026-08-03_2026-08-03.csv",
            "text/csv; charset=utf-8",
        )))
        return stack

    def _assert_stable(self, r, label: str) -> None:
        self.assertNotEqual(r.status_code, 500, f"{label} → 500 {r.text[:240]}")
        self.assertLess(r.status_code, 500, f"{label} → {r.status_code} {r.text[:240]}")
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/csv" in ctype or "application/zip" in ctype:
            self.assertEqual(r.status_code, 200, label)
            self.assertTrue(r.content, label)
            return
        body = r.json()
        self.assertIn("ok", body, label)
        self.assertIn("server_time", body, label)
        if r.status_code == 200:
            self.assertTrue(body.get("ok"), f"{label} {body}")
            self.assertIn("data", body, label)

    def test_catalog_covers_every_api_route(self) -> None:
        covered = {(m, p) for m, p, _, _ in PROBES}
        live = set()
        for route in self.app.routes:
            path = getattr(route, "path", "") or ""
            methods = getattr(route, "methods", None) or set()
            if not path.startswith("/api/v1/"):
                continue
            for method in methods:
                if method in ("HEAD", "OPTIONS"):
                    continue
                live.add((method, path))
        missing = sorted(live - covered)
        extra = sorted(covered - live)
        self.assertEqual(missing, [], msg=f"unprobed routes {missing}")
        self.assertEqual(extra, [], msg=f"probes for deleted routes {extra}")

    def test_every_probe_is_stable(self) -> None:
        snap = RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested
        try:
            with self._dhan_stack():
                for method, _tmpl, url, body in PROBES:
                    r = self.client.request(method, url, headers=self._h(), json=body)
                    self._assert_stable(r, f"{method} {url}")
        finally:
            RUNNER.state, RUNNER.mode, RUNNER.kill.active, RUNNER.stop_requested = snap

    def test_missing_required_query_is_4xx_not_500(self) -> None:
        with self._dhan_stack():
            for path in MISSING_QUERY:
                r = self.client.get(path, headers=self._h())
                self.assertIn(r.status_code, (400, 422), f"{path} → {r.status_code}")
                self.assertNotEqual(r.status_code, 500, path)
                self.assertFalse(r.json().get("ok"), path)

    def test_variant_trades_csv(self) -> None:
        r = self.client.get(
            "/api/v1/desk/research/variant-trades?pack_id=nifty_alpha&format=csv",
            headers=self._h(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers.get("content-type", ""))

    def test_token_post_does_not_write_env(self) -> None:
        with self._dhan_stack():
            from app.brokers.dhan import client as dhan

            r = self.client.post(
                "/api/v1/desk/system/token",
                headers=self._h(),
                json={"access_token": "must-not-persist", "client_id": "CLIENT9999", "generate_now": False},
            )
            self.assertEqual(r.status_code, 200)
            data = r.json()["data"]
            self.assertNotIn("must-not-persist", str(data))
            self.assertNotIn("LEAK", str(data))
            dhan.persist_env_vars.assert_called()
            dhan.set_access_token.assert_called()
            dhan.ensure_fresh_token.assert_called()

    def test_variant_sync_does_not_start_thread(self) -> None:
        with patch("app.main.research_tape_sync.start_sync", return_value={
            "ok": True, "started": False, "error": "up_to_date", "pack_id": "bn_alpha",
        }) as sync:
            r = self.client.post(
                "/api/v1/desk/research/variant-sync",
                headers=self._h(),
                json={"pack_id": "bn_alpha"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertFalse(r.json()["data"].get("started"))
        sync.assert_called_once()

    def test_quotes_option_quoted_not_stale_when_mocked(self) -> None:
        with self._dhan_stack():
            r = self.client.get(
                "/api/v1/desk/quotes/option?security_id=sid-qa&underlying=NIFTY",
                headers=self._h(),
            )
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertEqual(data.get("ltp"), 100.0)
        self.assertFalse(data.get("stale"))


if __name__ == "__main__":
    unittest.main()
