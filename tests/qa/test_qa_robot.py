"""QA robot: locked 4-variant board, envelopes, trail, visual harvest."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from app.auth import get_settings
from app.books.adapters import BookPaths, _fade_yaml_floats, sleeve_trail_params, variant_books
from app.research.stable import PAPER_VARIANTS, paper_pack, stable_catalog, yaml_allocation
from app.schemas.envelope import err, ok


ROOT = Path(__file__).resolve().parents[2]
HARVEST = ROOT / "reports" / "qa" / "harvest"


def _settings():
    os.environ["DESK_BFF_SECRET"] = ""
    os.environ.setdefault("DESK_API_KEY", "qa-desk-key")
    get_settings.cache_clear()
    return get_settings()


class TestLockedFourVariants(unittest.TestCase):
    def test_board_is_alpha_stable(self) -> None:
        self.assertEqual(len(PAPER_VARIANTS), 4)
        rels = {p.config_rel for p in PAPER_VARIANTS}
        self.assertEqual(
            rels,
            {
                "config/rungs/nifty_alpha.yaml",
                "config/rungs/nifty_stable.yaml",
                "config/rungs/bn_alpha.yaml",
                "config/rungs/bn_stable.yaml",
            },
        )
        self.assertEqual(paper_pack("nifty_alpha").selection, "primary")
        self.assertEqual(paper_pack("nifty_stable").selection, "secondary")
        self.assertEqual(paper_pack("bn_alpha").underlying, "BANKNIFTY")

    def test_yaml_files_exist_on_lab_roots(self) -> None:
        s = _settings()
        missing = []
        for pack in PAPER_VARIANTS:
            root = s.nifty_lab_root if pack.underlying == "NIFTY" else s.bn_lab_root
            path = root / pack.config_rel
            if not path.is_file():
                missing.append(str(path))
        self.assertEqual(missing, [], msg=f"locked YAML missing: {missing}")

    def test_allocation_and_recipe(self) -> None:
        s = _settings()
        expect = {
            "nifty_tier2_recommended": {"fade": 10, "orb": 0, "trail": 0.0, "capital": 200000},
            "nifty_ce400_secondary": {"fade": 10, "orb": 0, "trail": 0.0, "capital": 200000},
            "bn_f6o3_sm400_mce2": {"fade": 6, "orb": 3, "trail": 0.20, "capital": 200000},
            "bn_rs30_tp40_secondary": {"fade": 4, "orb": 0, "trail": 0.20, "capital": 200000},
        }
        for pack in PAPER_VARIANTS:
            root = s.nifty_lab_root if pack.underlying == "NIFTY" else s.bn_lab_root
            raw = yaml_allocation(root / pack.config_rel)
            want = expect[pack.pack_id]
            self.assertEqual(raw.get("total_capital_inr"), want["capital"], pack.pack_id)
            self.assertEqual(raw.get("fade_lots"), want["fade"], pack.pack_id)
            self.assertEqual(raw.get("orb_lots"), want["orb"], pack.pack_id)
            trail, act = _fade_yaml_floats(root / pack.config_rel, "trail_pct", "trail_activate_pct")
            self.assertAlmostEqual(trail, want["trail"], places=2, msg=pack.pack_id)
            if want["trail"] > 0:
                self.assertAlmostEqual(act, 0.20, places=2, msg=pack.pack_id)

    def test_sleeve_trail_fallback(self) -> None:
        s = _settings()
        bn = BookPaths("BANKNIFTY", s.bn_lab_root, "config/rungs/bn_alpha.yaml", s.bn_lab_root / "reports" / "shadow")
        nifty = BookPaths("NIFTY", s.nifty_lab_root, "config/rungs/nifty_alpha.yaml", s.nifty_lab_root / "reports" / "shadow")
        t, a = sleeve_trail_params(bn, "fade")
        self.assertAlmostEqual(t, 0.20, places=2)
        self.assertAlmostEqual(a, 0.20, places=2)
        t0, a0 = sleeve_trail_params(nifty, "fade")
        self.assertEqual((t0, a0), (0.0, 0.0))
        self.assertEqual(sleeve_trail_params(bn, "orb"), (0.0, 0.0))

    def test_catalog_from_real_labs(self) -> None:
        s = _settings()
        payload = stable_catalog(
            nifty_root=s.nifty_lab_root,
            bn_root=s.bn_lab_root,
            nifty_config=s.nifty_config,
            bn_config=s.bn_config,
        )
        rows = payload["paper_variants"]
        self.assertEqual(len(rows), 4)
        paper_err = [e for e in payload["errors"] if e.get("pack_id") in {p.pack_id for p in PAPER_VARIANTS}]
        self.assertEqual(paper_err, [])
        by_id = {r["pack_id"]: r for r in rows}
        self.assertTrue(by_id["nifty_tier2_recommended"]["config_exists"])
        self.assertTrue(by_id["bn_f6o3_sm400_mce2"]["config_exists"])
        bn = by_id["bn_f6o3_sm400_mce2"]
        self.assertGreater(float(bn["metrics"]["return_pct"]), 300)
        self.assertLess(float(bn["metrics"]["peak_dd_pct"]), 25)
        nifty = by_id["nifty_tier2_recommended"]
        self.assertLess(float(nifty["metrics"]["peak_dd_pct"]), 30)

    def test_home_books_are_four(self) -> None:
        s = _settings()
        books = variant_books(nifty_root=s.nifty_lab_root, bn_root=s.bn_lab_root)
        self.assertEqual(len(books), 4)
        self.assertEqual(books[0].display_name, "NIFTY Alpha")
        self.assertEqual(books[1].display_name, "NIFTY Stable")
        self.assertEqual(books[2].display_name, "BANKNIFTY Alpha")
        self.assertEqual(books[3].display_name, "BANKNIFTY Stable")


class TestEnvelope(unittest.TestCase):
    def test_ok_has_data(self) -> None:
        body = ok({"hello": 1})
        self.assertTrue(body["ok"])
        self.assertIn("server_time", body)
        self.assertTrue(str(body["server_time"]).endswith("Z"))
        self.assertEqual(body["data"]["hello"], 1)

    def test_err_is_not_200_shape_confusion(self) -> None:
        body = err("invalid or missing API key", code="unauthorized")
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "unauthorized")
        self.assertNotIn("data", body)


class TestHttpContract(unittest.TestCase):
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

    def _get(self, path: str, **kwargs):
        if not self.ready:
            self.skipTest(self.skip)
        return self.client.get(path, **kwargs)

    def test_healthz_no_key(self) -> None:
        r = self._get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))

    def test_status_401_without_key(self) -> None:
        r = self._get("/api/v1/desk/status")
        self.assertEqual(r.status_code, 401)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "unauthorized")

    def test_status_200_with_key(self) -> None:
        r = self._get("/api/v1/desk/status", headers={"X-API-Key": self.key})
        self.assertEqual(r.status_code, 200, r.json())
        body = r.json()
        self.assertTrue(body["ok"])
        data = body["data"]
        for key in ("mode", "runner_state", "trading_active", "books", "kill_switch_active"):
            self.assertIn(key, data, key)
        self.assertEqual(len(data.get("books") or []), 4)
        self.assertEqual(
            [b.get("label") for b in data["books"]],
            ["NIFTY Alpha", "NIFTY Stable", "BANKNIFTY Alpha", "BANKNIFTY Stable"],
        )

    def test_research_stable_four_variants(self) -> None:
        r = self._get("/api/v1/desk/research/stable", headers={"X-API-Key": self.key})
        self.assertEqual(r.status_code, 200, r.json())
        body = r.json()
        self.assertTrue(body["ok"])
        variants = body["data"].get("paper_variants") or []
        self.assertEqual(len(variants), 4)

    def test_readonly_routes_envelope(self) -> None:
        headers = {"X-API-Key": self.key}
        paths = (
            "/api/v1/desk/gates?underlying=NIFTY",
            "/api/v1/desk/positions",
            "/api/v1/desk/orders/open",
            "/api/v1/desk/trades/today",
            "/api/v1/desk/signals/today",
            "/api/v1/desk/signals/rejected",
            "/api/v1/desk/research/g5",
            "/api/v1/desk/safety/circuit-breaker",
            "/api/v1/desk/audit/tail",
            "/api/v1/desk/research/variant-summary?pack_id=nifty_alpha",
            "/api/v1/desk/runner",
            "/api/v1/desk/orders/queue",
            "/api/v1/desk/signals/last-cycle",
            "/api/v1/desk/safety/kill-switch",
            "/api/v1/desk/safety/shadow-book",
            "/api/v1/desk/research/oos",
            "/api/v1/desk/research/brief",
        )
        for path in paths:
            r = self._get(path, headers=headers)
            self.assertEqual(r.status_code, 200, f"{path} {r.json()}")
            body = r.json()
            self.assertTrue(body.get("ok"), path)
            self.assertIn("data", body, path)
            self.assertIn("server_time", body, path)


class TestVisualHarvest(unittest.TestCase):
    def test_write_harvest_snapshots(self) -> None:
        s = _settings()
        HARVEST.mkdir(parents=True, exist_ok=True)
        catalog = stable_catalog(
            nifty_root=s.nifty_lab_root,
            bn_root=s.bn_lab_root,
            nifty_config=s.nifty_config,
            bn_config=s.bn_config,
        )
        slim = []
        for row in catalog["paper_variants"]:
            slim.append(
                {
                    "pack_id": row["pack_id"],
                    "role": row["role"],
                    "selection": row["selection"],
                    "config_rel": row["config_rel"],
                    "config_exists": row["config_exists"],
                    "tape_exists": row.get("tape_exists"),
                    "metrics_source": row.get("metrics_source"),
                    "tape_stale": row.get("tape_stale"),
                    "paper_armed": row.get("paper_armed"),
                    "allocation": row.get("allocation"),
                    "metrics": row.get("metrics"),
                    "chart_count": (row.get("chart") or {}).get("count"),
                }
            )
        payload = {
            "desk_armed": catalog["desk_armed"],
            "errors": catalog["errors"],
            "paper_variants": slim,
        }
        dest = HARVEST / "paper_variants.json"
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        from app.books.adapters import books_snapshot, variant_books

        snap = books_snapshot(variant_books(nifty_root=s.nifty_lab_root, bn_root=s.bn_lab_root))
        (HARVEST / "home_books.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
        self.assertTrue(dest.is_file())
        self.assertEqual(len(slim), 4)
        self.assertTrue(all(v["config_exists"] for v in slim))
        self.assertEqual([b["label"] for b in snap], ["NIFTY Alpha", "NIFTY Stable", "BANKNIFTY Alpha", "BANKNIFTY Stable"])


if __name__ == "__main__":
    unittest.main()
