"""EOD Dhan → lab data_lake, independent of paper/live arming.

TOTP keeps the 24h access token alive. Charts ingest still needs an active
Dhan Data API plan (`dataPlan` on /profile). A never-expiring JWT is not required.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import zipfile
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.auth import get_settings
from app.runners.state import RUNNER
from app.session import IST, market_session, now_ist, session_day

MAX_DAYS_SPOT = 31
MAX_DAYS_OPTIONS = 7
CATCHUP_DAYS = 10
INGEST_AFTER = (15, 35)
_STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "lake_ingest.json"
_EXPORT = Path(__file__).resolve().parents[1] / "scripts" / "lake_csv_export.py"
_LOCK = threading.Lock()
_BUSY = False
_LAST: Dict[str, Any] = {
    "at": None,
    "ok": None,
    "detail": None,
    "last_ok_day": None,
    "ingest_through": None,
    "behind": None,
    "books": [],
    "data_plan": None,
    "data_validity": None,
    "max_days_spot": MAX_DAYS_SPOT,
    "max_days_options": MAX_DAYS_OPTIONS,
}


def status() -> Dict[str, Any]:
    row = dict(_LAST)
    disk = _load_state()
    for key in ("last_ok_day", "at", "ok", "detail", "books", "data_plan", "data_validity"):
        if row.get(key) in (None, [], "") and disk.get(key) not in (None, [], ""):
            row[key] = disk.get(key)
    latest = latest_ingest_day()
    last_ok = _parse_day(row.get("last_ok_day"))
    row["ingest_through"] = latest.isoformat()
    row["behind"] = last_ok is None or last_ok < latest
    row["max_days_spot"] = MAX_DAYS_SPOT
    row["max_days_options"] = MAX_DAYS_OPTIONS
    row["busy"] = _BUSY
    return row


def latest_ingest_day(at: Optional[datetime] = None) -> date:
    """Latest weekday whose Dhan session bars should be complete enough to store."""
    dt = at.astimezone(IST) if at is not None else now_ist()
    d = dt.date()
    sess = market_session(dt)
    if sess in ("pre", "open"):
        d = d - timedelta(days=1)
    elif sess == "closed" and dt.weekday() < 5 and (dt.hour, dt.minute) < INGEST_AFTER:
        d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d


def ingest_days(last_ok: Optional[date], latest: date, cap: int = CATCHUP_DAYS) -> List[date]:
    if last_ok is None:
        return [latest] if latest.weekday() < 5 else []
    start = last_ok + timedelta(days=1)
    out: List[date] = []
    d = start
    while d <= latest and len(out) < cap:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def clamp_export_range(
    from_day: str,
    to_day: str,
    kind: str,
    latest: Optional[date] = None,
) -> Optional[Tuple[date, date]]:
    try:
        start = date.fromisoformat(str(from_day)[:10])
        end = date.fromisoformat(str(to_day)[:10])
    except ValueError:
        return None
    if end < start:
        return None
    cap = MAX_DAYS_OPTIONS if str(kind).lower() in ("options", "both") else MAX_DAYS_SPOT
    if (end - start).days + 1 > cap:
        return None
    ceiling = latest or latest_ingest_day()
    if end > ceiling:
        return None
    return start, end


def tick() -> None:
    """Fill closed sessions into both lab lakes. Safe to call every few minutes."""
    global _BUSY
    if os.environ.get("DESK_LAKE_INGEST", "1").strip().lower() in ("0", "false", "no", "off"):
        return
    if _BUSY:
        return
    latest = latest_ingest_day()
    state = _load_state()
    last_ok = _parse_day(state.get("last_ok_day"))
    days = ingest_days(last_ok, latest)
    if not days:
        _LAST.update(
            {
                "ingest_through": latest.isoformat(),
                "last_ok_day": last_ok.isoformat() if last_ok else None,
                "behind": False,
            }
        )
        return
    last_fail = state.get("last_fail_at")
    if not state.get("ok", True) and last_fail and _seconds_since(last_fail) < 900:
        return
    with _LOCK:
        if _BUSY:
            return
        _BUSY = True
    try:
        _run_ingest(days, latest)
    finally:
        _BUSY = False


def export_file(
    *,
    underlying: str,
    kind: str,
    from_day: str,
    to_day: str,
) -> Tuple[bytes, str, str]:
    """CSV or zip of lake rows already on disk. Does not call Dhan."""
    und = str(underlying or "NIFTY").upper()
    k = str(kind or "spot").lower()
    if und not in ("NIFTY", "BANKNIFTY", "ALL"):
        raise ValueError("underlying must be NIFTY, BANKNIFTY, or ALL")
    if k not in ("spot", "options", "both"):
        raise ValueError("kind must be spot, options, or both")
    span = clamp_export_range(from_day, to_day, k)
    if not span:
        cap = MAX_DAYS_OPTIONS if k in ("options", "both") else MAX_DAYS_SPOT
        raise ValueError(f"range must be on disk, not future, and at most {cap} days")
    start, end = span
    books = ["NIFTY", "BANKNIFTY"] if und == "ALL" else [und]
    kinds = ["spot", "options"] if k == "both" else [k]
    parts: List[Tuple[str, bytes]] = []
    for book in books:
        for asset in kinds:
            raw = _export_csv(book, asset, start, end)
            parts.append((f"{book.lower()}_{asset}_{start.isoformat()}_{end.isoformat()}.csv", raw))
    if len(parts) == 1:
        name, body = parts[0]
        return body, name, "text/csv; charset=utf-8"
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in parts:
            zf.writestr(name, body)
    zip_name = f"lake_{und.lower()}_{k}_{start.isoformat()}_{end.isoformat()}.zip"
    return buf.getvalue(), zip_name, "application/zip"


def _run_ingest(days: List[date], latest: date) -> None:
    from app.brokers.dhan import client as dhan

    start, end = days[0], days[-1]
    try:
        dhan.ensure_fresh_token()
    except Exception:
        pass
    plan = _data_plan()
    s = get_settings()
    py = _lab_python()
    books = [
        _ingest_one(py, s.nifty_lab_root, "scripts/ingest_dhan_nifty.py", start, end),
        _ingest_one(py, s.bn_lab_root, "scripts/ingest_dhan_bn.py", start, end),
    ]
    ok = all(b.get("ok") for b in books)
    empty_ok = _accept_empty(days[-1])
    if not ok:
        detail = "; ".join(str(b.get("detail") or "")[:80] for b in books)
        _save_state(
            {
                "ok": False,
                "at": _now_z(),
                "last_fail_at": _now_z(),
                "detail": detail,
                "last_ok_day": (_load_state().get("last_ok_day")),
                "books": books,
                **plan,
            }
        )
        RUNNER.audit_event("lake.ingest", ok=False, from_day=start.isoformat(), to_day=end.isoformat())
        return
    probes = [_probe_book("NIFTY", s.nifty_lab_root, days[-1]), _probe_book("BANKNIFTY", s.bn_lab_root, days[-1])]
    bars = [int(p.get("rows") or 0) for p in probes]
    if max(bars) == 0 and not empty_ok:
        _save_state(
            {
                "ok": False,
                "at": _now_z(),
                "last_fail_at": _now_z(),
                "detail": "Dhan returned no bars yet — will retry",
                "last_ok_day": _load_state().get("last_ok_day"),
                "books": probes,
                **plan,
            }
        )
        return
    _save_state(
        {
            "ok": True,
            "at": _now_z(),
            "last_fail_at": None,
            "detail": f"ingested {start.isoformat()} → {end.isoformat()}",
            "last_ok_day": end.isoformat(),
            "books": probes,
            **plan,
        }
    )
    RUNNER.audit_event("lake.ingest", ok=True, from_day=start.isoformat(), to_day=end.isoformat())
    _LAST["ingest_through"] = latest.isoformat()
    _LAST["behind"] = False


def _ingest_one(py: str, lab: Path, script: str, start: date, end: date) -> Dict[str, Any]:
    path = lab / script
    if not path.exists():
        return {"ok": False, "lab": str(lab), "detail": f"{script} missing"}
    try:
        proc = subprocess.run(
            [
                py,
                str(path),
                "--from",
                start.isoformat(),
                "--to",
                end.isoformat(),
                "--n-strikes",
                "6",
                "--max-contracts",
                "30",
            ],
            cwd=str(lab),
            capture_output=True,
            text=True,
            timeout=900,
            env={**os.environ},
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "lab": str(lab), "detail": str(exc)[:240]}
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-400:]
    return {"ok": proc.returncode == 0, "lab": str(lab), "detail": out or f"exit {proc.returncode}", "code": proc.returncode}


def _probe_book(und: str, lab: Path, day: date) -> Dict[str, Any]:
    try:
        raw = _run_export(lab, und, "probe", "spot", day, day, out="")
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except Exception as exc:  # noqa: BLE001
        data = {"error": str(exc)[:240], "rows": 0}
    data["underlying"] = und
    try:
        opt = _run_export(lab, und, "probe", "options", day, day, out="")
        odata = json.loads(opt.decode("utf-8") if isinstance(opt, bytes) else opt)
        data["option_rows"] = odata.get("rows")
    except Exception:
        data["option_rows"] = None
    return data


def _export_csv(und: str, kind: str, start: date, end: date) -> bytes:
    import tempfile

    s = get_settings()
    lab = s.nifty_lab_root if und == "NIFTY" else s.bn_lab_root
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    try:
        _run_export(lab, und, "csv", kind, start, end, out=path)
        return Path(path).read_bytes()
    finally:
        Path(path).unlink(missing_ok=True)


def _run_export(lab: Path, und: str, mode: str, kind: str, start: date, end: date, out: str) -> bytes:
    py = _lab_python()
    cmd = [
        py,
        str(_EXPORT),
        "--lab-root",
        str(lab),
        "--underlying",
        und,
        "--mode",
        mode,
        "--kind",
        kind,
        "--from",
        start.isoformat(),
        "--to",
        end.isoformat(),
    ]
    if out:
        cmd.extend(["--out", out])
    proc = subprocess.run(
        cmd,
        cwd=str(lab),
        capture_output=True,
        timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace")[-240:]
        raise RuntimeError(err or f"export exit {proc.returncode}")
    return proc.stdout or b""


def _lab_python() -> str:
    s = get_settings()
    for root in (s.bn_lab_root, s.nifty_lab_root):
        for rel in (".venv/bin/python3", ".venv/Scripts/python.exe"):
            p = Path(root) / rel
            if p.exists():
                return str(p)
    return sys.executable


def _data_plan() -> Dict[str, Any]:
    try:
        from app.brokers.dhan import client as dhan

        return dhan.data_plan_status()
    except Exception:
        return {"data_plan": None, "data_validity": None}


def _accept_empty(day: date) -> bool:
    now = now_ist()
    if day < session_day():
        return True
    return now.hour >= 16


def _parse_day(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _load_state() -> Dict[str, Any]:
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(row: Dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(row, indent=2), encoding="utf-8")
    _LAST.update(row)


def _now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _seconds_since(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return 1e9
