"""Smoke D1–D8 desk routes against a running local desk (default :8080)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_key() -> str:
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DESK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DESK_API_KEY", "")


def get(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={"X-API-Key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    base = os.environ.get("DESK_SMOKE_BASE", "http://127.0.0.1:8080/api/v1/desk")
    key = _load_key()
    if not key:
        print("FAIL: DESK_API_KEY missing", file=sys.stderr)
        return 2
    checks = [
        ("gates?underlying=NIFTY", lambda d: "premium_budget" in (d.get("sleeves") or [{}])[0]),
        ("research/g5", lambda d: isinstance(d.get("books"), list)),
        ("research/oos?underlying=NIFTY", lambda d: isinstance(d.get("windows"), list)),
        ("research/cost-honesty?underlying=BANKNIFTY", lambda d: "available" in d),
        ("research/scale?underlying=BANKNIFTY", lambda d: isinstance(d.get("rows"), list)),
        ("research/brief", lambda d: isinstance(d.get("books"), list)),
        ("signals/rejected", lambda d: "rows" in d and (not d["rows"] or "stage" in d["rows"][0])),
        ("safety/circuit-breaker", lambda d: "books" in d and "peak_dd_pct" in d),
        ("audit/tail?limit=5", lambda d: "events" in d and "limit" in d),
    ]
    failed = 0
    for path, pred in checks:
        url = f"{base}/{path}"
        try:
            env = get(url, key)
            data = env.get("data") if isinstance(env, dict) else None
            ok = bool(env.get("ok")) and isinstance(data, dict) and pred(data)
            print(("OK" if ok else "BAD"), path)
            if not ok:
                failed += 1
        except urllib.error.HTTPError as exc:
            print("FAIL", path, exc.code)
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print("FAIL", path, exc)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
