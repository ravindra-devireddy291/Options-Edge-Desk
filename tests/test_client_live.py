"""Local client accounts: SQLite, sizing, and the live routes. No VPS and no Groww network."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ["DESK_API_KEY"] = "test-desk-key"
os.environ["DESK_BFF_SECRET"] = ""
os.environ["GROWW_MODE"] = "local"
os.environ["GROWW_LINK_KEY"] = "test-groww-link-key"
os.environ["CLIENT_LIVE_DB"] = str(Path(tempfile.mkdtemp()) / "clients.sqlite")

from app.auth import get_settings  # noqa: E402
from app.client_live import (  # noqa: E402
    create_client,
    is_client_role,
    login,
    me_live,
    notify_edge,
    refresh_access,
    register,
    set_wallet,
)
from app.client_routes import router  # noqa: E402
from app.client_store import connect, open_seal  # noqa: E402

get_settings.cache_clear()

TOKEN = "x" * 20
SECRET = "secret12"


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _headers(email: str, role: str) -> dict:
    return {"X-API-Key": "test-desk-key", "X-Desk-User": email, "X-Desk-Role": role}


class TestClientLive(unittest.TestCase):
    def setUp(self) -> None:
        path = Path(tempfile.mkdtemp()) / "clients.sqlite"
        os.environ["CLIENT_LIVE_DB"] = str(path)
        with connect() as conn:
            conn.commit()

    def test_register_hides_secret_and_sizes_two_wallets(self) -> None:
        create_client("asha@client.com", "pw-asha", "client")
        create_client("dev@client.com", "pw-dev", "client")
        live = register(
            "asha@client.com",
            {
                "full_name": "Asha Rao",
                "mobile": "9876543210",
                "totp_token": TOKEN,
                "totp_secret": SECRET,
                "live_confirmed": True,
            },
        )
        register(
            "dev@client.com",
            {
                "full_name": "Dev Rao",
                "mobile": "9876543211",
                "totp_token": TOKEN,
                "totp_secret": SECRET,
                "live_confirmed": True,
            },
        )
        self.assertEqual(live["link"]["status"], "linked")
        self.assertNotIn(SECRET, json.dumps(live))
        with connect() as conn:
            sealed = conn.execute(
                "SELECT totp_secret_enc FROM groww_links WHERE email = ?",
                ("asha@client.com",),
            ).fetchone()["totp_secret_enc"]
        self.assertEqual(open_seal(sealed), SECRET)
        self.assertNotIn(SECRET, sealed)
        set_wallet("asha@client.com", 200000, 50000, 10)
        set_wallet("dev@client.com", 40000, 50000, 10)
        from app.client_live import set_auto

        set_auto("asha@client.com", True)
        set_auto("dev@client.com", True)
        notify_edge("edge-1", "NIFTY 24500 CE", "buy", "NIFTY", 24500, "CE")
        asha = me_live("asha@client.com")
        dev = me_live("dev@client.com")
        self.assertEqual(asha["last_order"]["state"], "filled")
        self.assertEqual(asha["last_order"]["lots"], 4)
        self.assertEqual(dev["last_order"]["state"], "skipped")
        self.assertEqual(dev["last_order"]["lots"], 0)
        self.assertIsNone(asha["pending_edge"])

    def test_manual_accept_and_reject(self) -> None:
        create_client("mina@client.com", "pw", "client")
        register(
            "mina@client.com",
            {
                "full_name": "Mina Rao",
                "mobile": "9123456789",
                "totp_token": TOKEN,
                "totp_secret": SECRET,
                "live_confirmed": True,
            },
        )
        set_wallet("mina@client.com", 900000, 50000, 10)
        notify_edge("edge-2", "BANKNIFTY 52000 PE", "sell", "BANKNIFTY", 52000, "PE")
        pending = me_live("mina@client.com")["pending_edge"]
        self.assertEqual(pending["edge_id"], "edge-2")
        from app.client_live import decide

        rejected = decide("mina@client.com", "edge-2", "reject")
        self.assertEqual(rejected["last_order"]["state"], "rejected")
        self.assertEqual(rejected["last_order"]["lots"], 0)
        notify_edge("edge-3", "NIFTY 24500 CE", "buy", "NIFTY", 24500, "CE")
        accepted = decide("mina@client.com", "edge-3", "accept")
        self.assertEqual(accepted["last_order"]["lots"], 10)
        self.assertEqual(accepted["last_order"]["state"], "filled")

    def test_login_and_routes(self) -> None:
        create_client("ops@desk.com", "ops-secret", "admin")
        create_client("asha@client.com", "pw-asha", "client")
        self.assertEqual(login("ops@desk.com", "ops-secret")["role"], "admin")
        self.assertIsNone(login("ops@desk.com", "nope"))
        client = _app()
        headers = _headers("asha@client.com", "client")
        reg = client.post(
            "/api/v1/desk/me/register",
            headers=headers,
            json={
                "full_name": "Asha Rao",
                "mobile": "9876543210",
                "totp_token": TOKEN,
                "totp_secret": SECRET,
                "live_confirmed": True,
            },
        )
        self.assertEqual(reg.status_code, 200)
        self.assertEqual(reg.json()["data"]["link"]["status"], "linked")
        roster = client.get("/api/v1/desk/clients/live", headers=headers)
        self.assertEqual(roster.status_code, 403)
        admin = client.get("/api/v1/desk/clients/live", headers=_headers("ops@desk.com", "admin"))
        self.assertEqual(admin.status_code, 200)
        self.assertEqual(admin.json()["data"][0]["email"], "asha@client.com")
        self.assertNotIn("totp", json.dumps(admin.json()))
        bad = client.post(
            "/api/v1/desk/auth/login",
            headers={"X-API-Key": "test-desk-key"},
            json={"email": "ops@desk.com", "password": "nope"},
        )
        self.assertEqual(bad.status_code, 401)
        good = client.post(
            "/api/v1/desk/auth/login",
            headers={"X-API-Key": "test-desk-key"},
            json={"email": "asha@client.com", "password": "pw-asha"},
        )
        self.assertEqual(good.json()["data"]["role"], "client")
        self.assertTrue(is_client_role("client"))

    def test_client_paper_order_is_refused(self) -> None:
        from starlette.requests import Request

        from app.main import PaperOrderBody, paper_order

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"x-desk-role", b"client"), (b"x-desk-user", b"asha@client.com")],
            "query_string": b"",
        }
        body = PaperOrderBody(
            underlying="NIFTY",
            lots=1,
            strike=24500,
            option_type="CE",
            expiry="2026-10-22",
            dry_run=True,
        )
        res = paper_order(body, Request(scope))
        self.assertEqual(res.status_code, 403)

    def test_stop_skips_pending_and_refresh_marks_reconnect(self) -> None:
        create_client("asha@client.com", "pw", "client")
        register(
            "asha@client.com",
            {
                "full_name": "Asha Rao",
                "mobile": "9876543210",
                "totp_token": TOKEN,
                "totp_secret": SECRET,
                "live_confirmed": True,
            },
        )
        notify_edge("edge-9", "NIFTY 24500 CE", "buy")
        from app.client_live import stop_orders

        stopped = stop_orders("asha@client.com")
        self.assertEqual(stopped["last_order"]["state"], "skipped")
        os.environ["GROWW_MODE"] = "live"

        class Boom:
            def session(self, token: str, secret: str):
                raise RuntimeError("down")

        import app.client_live as live

        original = live.gateway
        live.gateway = lambda: Boom()
        try:
            result = refresh_access()
        finally:
            live.gateway = original
            os.environ["GROWW_MODE"] = "local"
        self.assertEqual(result["reconnect"], 1)
        self.assertEqual(me_live("asha@client.com")["link"]["status"], "reconnect")


if __name__ == "__main__":
    unittest.main()
