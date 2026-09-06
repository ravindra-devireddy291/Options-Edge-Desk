"""Desk QA robot — unittest + harvest report (no live VPS / broker required)."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "qa"
sys.path.insert(0, str(ROOT))


def _run() -> unittest.TestResult:
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


def _write_report(result: unittest.TestResult) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    harvest = OUT / "harvest"
    screens = []
    if harvest.is_dir():
        screens = sorted(p.name for p in harvest.iterdir() if p.suffix in (".json", ".png", ".md"))
    failed = result.failures + result.errors
    rows = []
    for case, _ in result.failures:
        rows.append(("failed", case.id()))
    for case, _ in result.errors:
        rows.append(("error", case.id()))
    passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
    md = [
        "# Options Edge Desk — QA robot report",
        "",
        f"Generated {datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')}",
        "",
        "| Passed | Failed | Errors | Skipped | Harvest files |",
        "| --- | --- | --- | --- | --- |",
        f"| {passed} | {len(result.failures)} | {len(result.errors)} | {len(result.skipped)} | {len(screens)} |",
        "",
        "## Failures",
        "",
    ]
    if not failed:
        md.append("_None._")
    else:
        for status, ident in rows:
            md.append(f"- `{status}` `{ident}`")
    md += [
        "",
        "## Harvest",
        "",
    ]
    md.extend(f"- `reports/qa/harvest/{name}`" for name in screens) if screens else md.append("_No harvest._")
    md += [
        "",
        "## What this proves",
        "",
        "- Four client-locked paper books are **Nifty Alpha / Nifty Stable / BN Alpha / BN Stable**.",
        "- Locked YAML files exist on lab roots; BN trail 20@20; Nifty fade has no trail.",
        "- Envelope 401 without key; 200 + `data` with key. Healthz needs no key.",
        "- Paper OMS survives a process-style reload from disk; corrupt ledger does not crash.",
        "- Place idempotency cache returns the original payload. Trail stop never drops below the YAML floor.",
        "- Desk is tested without the live VPS or Dhan money (FastAPI TestClient).",
        "- Paper 360: Nifty **and** BN Alpha **and** Stable buy/sell; four research packs take paper fills; live stays off even at G5=20.",
        "- Successful paper place no longer crashes audit (`trace_id` double-kwarg).",
        "- Paper YAML stop / TP / trail fire on live LTP; BN trail 20@20; Nifty floor 30% / TP 50%.",
        "- Auto EOD flatten, archive, and `/positions` read the paper ledger (not Dhan) while live is off.",
        "- Cancel of `paper_*` / ledger ids is ALREADY_FILLED; unknown `desk-*` still goes to Dhan.",
        "- Schedule arms paper not live; kill blocks tick; HTTP start/stop/kill/ack/WS are covered.",
        "- OpenAPI `/docs` is off. HTTP auth is header-only (no `?api_key=`). Lab tape cannot stuff Gate 5.",
        "- Token HTTP view masks client id and drops token prefix. Every `/api/v1` route 401s without a key.",
        "- UI-only access: `X-Desk-BFF` required when `DESK_BFF_SECRET` is set; CORS is empty; browsers cannot call deskapi.",
        "- Route matrix: every `/api/v1` GET/POST is probed with a key; missing required query is 4xx; **never 500**; Dhan HTTP is patched out (token set cannot write `.env`).",
        "- Load soak: concurrent healthz/status/snapshot + WS burst (see `harvest/load_inproc.json`). VPS soak: `scripts/_load_desk_vps.py` → `harvest/load_vps.json`.",
        "",
    ]
    dest = OUT / "QA_REPORT.md"
    dest.write_text("\n".join(md), encoding="utf-8")
    summary = {
        "passed": passed,
        "failed": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "testsRun": result.testsRun,
        "ok": result.wasSuccessful(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return dest


def main() -> int:
    result = _run()
    dest = _write_report(result)
    print(f"QA report {dest} ok={result.wasSuccessful()}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
