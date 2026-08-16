"""Durable desk event log (IST day files). Survives process restart."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.session import session_day


def _audit_dir() -> Path:
    from app.auth import get_settings

    path = get_settings().audit_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def events_path(day: str | None = None) -> Path:
    day = day or session_day().isoformat()
    return _audit_dir() / f"events_{day}.jsonl"


def append_event(kind: str, **payload: Any) -> Dict[str, Any]:
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    row = {"ts": ts, "kind": kind, **payload}
    path = events_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return row


def load_today(limit: int = 400) -> List[Dict[str, Any]]:
    path = events_path()
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows[-max(1, min(limit, 500)) :]


def count_today() -> int:
    path = events_path()
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0
