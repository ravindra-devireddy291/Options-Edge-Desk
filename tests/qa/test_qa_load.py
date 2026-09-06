"""Invite-desk soak: concurrent healthz/status/snapshot + WS. No Dhan place."""
from __future__ import annotations

import json
import os
import statistics
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.auth import get_settings

HARVEST = Path(__file__).resolve().parents[2] / "reports" / "qa" / "harvest"


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
    return round(s[k] * 1000, 1)


class TestDeskLoad(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["DESK_BFF_SECRET"] = ""
        os.environ.setdefault("DESK_API_KEY", "qa-desk-key")
        get_settings.cache_clear()
        from fastapi.testclient import TestClient
        from app.main import app

        cls.key = get_settings().desk_api_key
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.h = {"X-API-Key": cls.key}

    def _timed(self, fn) -> tuple[int, float]:
        t0 = time.perf_counter()
        r = fn()
        return r.status_code, time.perf_counter() - t0

    def test_concurrent_readonly_soak(self) -> None:
        with patch("app.brokers.dhan.client._request", side_effect=AssertionError("Dhan HTTP in load QA")):
            with patch("app.brokers.dhan.client.token_status", return_value={"token_ok": True, "has_access_token": True}):
                with patch("app.brokers.dhan.client.spots_with_change", return_value={
                    "NIFTY": {"ltp": 24000.0, "change_pct": 0.1, "change_pts": 24.0},
                    "BANKNIFTY": {"ltp": 52000.0, "change_pct": -0.1, "change_pts": -52.0},
                }):
                    with patch("app.brokers.dhan.client.broker_reachable", return_value=True):
                        with patch("app.brokers.dhan.client.available_cash", return_value=1_000_000.0):
                            hz, st, sn = self._burst()
        self._assert_ok("healthz", hz, expect=200, p95_ms=500)
        self._assert_ok("status", st, expect=200, p95_ms=4000)
        self._assert_ok("snapshot", sn, expect=200, p95_ms=4000)
        HARVEST.mkdir(parents=True, exist_ok=True)
        payload = {
            "target": "inproc TestClient",
            "healthz": _summary(hz),
            "status": _summary(st),
            "snapshot": _summary(sn),
        }
        (HARVEST / "load_inproc.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _burst(self) -> tuple[list, list, list]:
        hz: list[tuple[int, float]] = []
        st: list[tuple[int, float]] = []
        sn: list[tuple[int, float]] = []
        jobs = []
        with ThreadPoolExecutor(max_workers=16) as pool:
            for _ in range(160):
                jobs.append(("hz", pool.submit(self._timed, lambda: self.client.get("/healthz"))))
            for _ in range(48):
                jobs.append(("st", pool.submit(self._timed, lambda: self.client.get("/api/v1/desk/status", headers=self.h))))
            for _ in range(24):
                jobs.append(("sn", pool.submit(self._timed, lambda: self.client.get("/api/v1/desk/snapshot", headers=self.h))))
            for kind, fut in jobs:
                code, sec = fut.result(timeout=30)
                if kind == "hz":
                    hz.append((code, sec))
                elif kind == "st":
                    st.append((code, sec))
                else:
                    sn.append((code, sec))
        return hz, st, sn

    def _assert_ok(self, name: str, rows: list[tuple[int, float]], *, expect: int, p95_ms: float) -> None:
        codes = [c for c, _ in rows]
        lat = [s for _, s in rows]
        self.assertTrue(rows, name)
        self.assertNotIn(500, codes, f"{name} had 500s")
        self.assertEqual(codes.count(expect), len(codes), f"{name} codes={set(codes)}")
        self.assertLessEqual(_pct(lat, 95), p95_ms, f"{name} p95={_pct(lat, 95)}ms")

    def test_ws_connect_burst(self) -> None:
        ok = 0
        for _ in range(12):
            with self.client.websocket_connect("/ws/desk", headers=self.h) as ws:
                msg = ws.receive_json()
                self.assertEqual(msg.get("type"), "connected")
                ok += 1
        self.assertEqual(ok, 12)


def _summary(rows: list[tuple[int, float]]) -> dict:
    lat = [s for _, s in rows]
    return {
        "n": len(rows),
        "ok": sum(1 for c, _ in rows if c == 200),
        "p50_ms": _pct(lat, 50),
        "p95_ms": _pct(lat, 95),
        "max_ms": round(max(lat) * 1000, 1) if lat else 0,
        "mean_ms": round(statistics.mean(lat) * 1000, 1) if lat else 0,
    }
