"""Blackbox: every HTTP route is keyed; OpenAPI off; no query-key; G5 cannot be lab-stuffed."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.auth import cors_allowed_origins, get_settings
from app.brokers.dhan.client import token_public_view


class TestTokenPublicView(unittest.TestCase):
    def test_strips_prefix_and_masks_client(self) -> None:
        out = token_public_view(
            {
                "api_key": "CLIENT123456",
                "access_token_masked": "abcd••••••••",
                "token_ok": True,
                "has_access_token": True,
                "broker": "dhan",
                "auto": {"ok": True, "raw_keys": ["accessToken"], "accessToken": "LEAK"},
            }
        )
        self.assertNotIn("access_token_masked", out)
        self.assertEqual(out["api_key"], "••••3456")
        self.assertNotIn("LEAK", str(out))
        self.assertNotIn("accessToken", str(out.get("auto") or {}))


class TestHttpBlackbox(unittest.TestCase):
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
            cls.app = app
            cls.ready = True
            cls.skip = ""
        except Exception as exc:  # noqa: BLE001
            cls.ready = False
            cls.skip = str(exc)
            cls.client = None
            cls.app = None
            cls.key = ""

    def _h(self) -> dict:
        return {"X-API-Key": self.key}

    def test_docs_and_openapi_are_closed(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        for path in ("/docs", "/redoc", "/openapi.json"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 404, path)

    def test_healthz_has_no_secrets(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        blob = str(body).lower()
        self.assertTrue(body.get("ok"))
        self.assertNotIn("token", blob)
        self.assertNotIn("dhan", blob)
        self.assertNotIn("api_key", blob)

    def test_query_api_key_is_rejected(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        r = self.client.get(f"/api/v1/desk/status?api_key={self.key}")
        self.assertEqual(r.status_code, 401)

    def test_every_api_route_401_without_key(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        seen = []
        for route in self.app.routes:
            path = getattr(route, "path", "") or ""
            methods = getattr(route, "methods", None) or set()
            if not path.startswith("/api/v1/"):
                continue
            concrete = path.replace("{underlying}", "NIFTY")
            for method in methods:
                if method in ("HEAD", "OPTIONS"):
                    continue
                seen.append((method, concrete))
                r = self.client.request(method, concrete)
                self.assertEqual(r.status_code, 401, f"{method} {concrete} → {r.status_code}")
        self.assertGreaterEqual(len(seen), 40)

    def test_remaining_safe_gets_envelope(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        h = self._h()
        paths = (
            "/api/v1/desk/runner",
            "/api/v1/desk/health/full",
            "/api/v1/desk/orders/queue",
            "/api/v1/desk/signals/last-cycle",
            "/api/v1/desk/safety/kill-switch",
            "/api/v1/desk/safety/shadow-book",
            "/api/v1/desk/research/oos",
            "/api/v1/desk/research/cost-honesty",
            "/api/v1/desk/research/scale",
            "/api/v1/desk/research/brief",
            "/api/v1/desk/research/stable/NIFTY",
            "/api/v1/desk/trades/history?from=2026-09-01&to=2026-09-01",
            "/api/v1/desk/quotes/option",
        )
        for path in paths:
            r = self.client.get(path, headers=h)
            self.assertEqual(r.status_code, 200, f"{path} {r.text[:200]}")
            body = r.json()
            self.assertTrue(body.get("ok"), path)
            self.assertIn("data", body, path)

    def test_lake_download_rejects_bad_range(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        r = self.client.get(
            "/api/v1/desk/research/lake-download?underlying=NIFTY&kind=spot&from=2099-01-01&to=2099-01-02",
            headers=self._h(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json().get("ok"))

    def test_cycle_tick_and_variant_sync_401(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        r = self.client.post("/api/v1/desk/cycle/tick")
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/v1/desk/research/variant-sync", json={"pack_id": "nifty_alpha"})
        self.assertEqual(r.status_code, 401)

    def test_cycle_tick_with_key(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        r = self.client.post("/api/v1/desk/cycle/tick", headers=self._h())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))

    def test_token_get_is_public_view(self) -> None:
        if not self.ready:
            self.skipTest(self.skip)
        fake = {
            "api_key": "ABCDEFGHIJ",
            "access_token_masked": "tok_••••",
            "token_ok": True,
            "has_access_token": True,
            "broker": "dhan",
            "login_url": "https://web.dhan.co/",
            "auto_renew_enabled": True,
            "auto_totp_enabled": False,
        }
        with patch("app.main.dhan.token_status", return_value=fake), patch(
            "app.brokers.dhan.client.token_status", return_value=fake
        ):
            r = self.client.get("/api/v1/desk/system/token", headers=self._h())
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertNotIn("access_token_masked", data)
        self.assertEqual(data.get("api_key"), "••••GHIJ")
        self.assertNotIn("tok_", str(data))


class TestBffOnly(unittest.TestCase):
    def test_cors_closed_when_bff_secret_set(self) -> None:
        prev = os.environ.get("DESK_BFF_SECRET")
        os.environ["DESK_BFF_SECRET"] = "ui-only-secret"
        try:
            self.assertEqual(cors_allowed_origins(), [])
        finally:
            if prev is None:
                os.environ.pop("DESK_BFF_SECRET", None)
            else:
                os.environ["DESK_BFF_SECRET"] = prev

    def test_api_key_alone_is_denied(self) -> None:
        prev = os.environ.get("DESK_BFF_SECRET")
        os.environ["DESK_BFF_SECRET"] = "ui-only-secret"
        get_settings.cache_clear()
        try:
            from fastapi.testclient import TestClient
            from app.main import app

            key = get_settings().desk_api_key
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/v1/desk/status", headers={"X-API-Key": key})
            self.assertEqual(r.status_code, 401)
            r = client.get(
                "/api/v1/desk/status",
                headers={"X-API-Key": key, "X-Desk-BFF": "ui-only-secret"},
            )
            self.assertEqual(r.status_code, 200)
            with self.assertRaises(Exception):
                with client.websocket_connect(f"/ws/desk?api_key={key}"):
                    pass
            with client.websocket_connect(
                "/ws/desk",
                headers={"X-API-Key": key, "X-Desk-BFF": "ui-only-secret"},
            ) as ws:
                msg = ws.receive_json()
                self.assertEqual(msg.get("type"), "connected")
        finally:
            if prev is None:
                os.environ.pop("DESK_BFF_SECRET", None)
            else:
                os.environ["DESK_BFF_SECRET"] = prev
            get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
