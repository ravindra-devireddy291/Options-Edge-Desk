"""Run Edge Lab shadow journals during the NSE cash window.

Paper/live compass is today's lab JSONL. This keeper invokes each lab's
`run_shadow_journal.py` when those scripts exist. Failures are logged; the
desk never invents PENDING cards.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.auth import get_settings
from app.runners.state import RUNNER
from app.session import market_session, now_ist

_LAST: Dict[str, Any] = {
    "at": None,
    "ok": None,
    "detail": None,
    "books": [],
}


def status() -> Dict[str, Any]:
    return dict(_LAST)


def _run_journal(lab_root: Path, config: str, py: str, *, skip_ingest: bool = False) -> Dict[str, Any]:
    daily = lab_root / "scripts" / "run_shadow_daily.py"
    journal = lab_root / "scripts" / "run_shadow_journal.py"
    day = now_ist().date().isoformat()
    if daily.exists():
        cmd = [py, str(daily), "--day", day, "--config", config, "--skip-sync"]
        if skip_ingest:
            cmd.append("--skip-ingest")
    elif journal.exists():
        cmd = [py, str(journal), "--day", day, "--config", config, "--replace"]
    else:
        return {"ok": False, "lab": str(lab_root), "detail": "run_shadow_daily.py / run_shadow_journal.py missing"}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(lab_root),
            capture_output=True,
            text=True,
            timeout=420,
            env={**os.environ},
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "lab": str(lab_root), "detail": str(exc)[:240]}
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-400:]
    return {
        "ok": proc.returncode == 0,
        "lab": str(lab_root),
        "detail": out or f"exit {proc.returncode}",
        "code": proc.returncode,
    }


def tick() -> None:
    """At most one journal pass per call; skip outside cash hours and in mock."""
    mode = (RUNNER.mode or "").lower()
    if mode not in ("paper", "live"):
        return
    now = now_ist()
    if now.weekday() >= 5:
        return
    if market_session() not in ("pre", "open"):
        return
    s = get_settings()
    py = sys.executable
    venv = Path("/root/Options-Edge-Lab/.venv/bin/python3")
    if venv.exists():
        py = str(venv)
    from app.research.stable import PAPER_VARIANTS

    seen_und: set[str] = set()
    books: List[Dict[str, Any]] = []
    for pack in PAPER_VARIANTS:
        root = s.nifty_lab_root if pack.underlying == "NIFTY" else s.bn_lab_root
        skip_ingest = pack.underlying in seen_und
        seen_und.add(pack.underlying)
        row = _run_journal(root, pack.config_rel, py, skip_ingest=skip_ingest)
        row["pack_id"] = pack.pack_id
        row["config"] = pack.config_rel
        books.append(row)
    ok = all(b.get("ok") for b in books)
    _LAST.update(
        {
            "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "ok": ok,
            "detail": "; ".join(str(b.get("detail") or "")[:80] for b in books),
            "books": books,
        }
    )
    RUNNER.audit_event(
        "lab.journal",
        ok=ok,
        n=len(books),
        packs=[b.get("pack_id") for b in books],
    )
