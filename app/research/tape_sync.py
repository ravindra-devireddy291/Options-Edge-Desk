"""Fill missing locked-tape days from last trade through the day before paper start."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.books import adapters as books
from app.research.stable import PACK_ALIASES, PackDef, paper_pack
from app.session import market_session, session_day

LOCKED_START = date(2021, 7, 1)
_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}

# pack_id -> (lab, recipe key, tape_rel)
_EXPORT: Dict[str, Tuple[str, str, str]] = {
    "nifty_tier2_recommended": ("nifty", "tier2_recommended", "reports/nifty_trades_tier2_recommended_2l.json"),
    "nifty_ce400_secondary": ("nifty", "ce400_secondary", "reports/nifty_trades_ce400_secondary_2l.json"),
    "bn_f6o3_sm400_mce2": ("bn", "f6o3_sm400_mce2", "reports/bn_trades_f6o3_sm400_mce2_2l.json"),
    "bn_rs30_tp40_secondary": ("bn", "rs30_tp40_secondary", "reports/bn_trades_rs30_tp40_secondary_2l.json"),
}


def _spec(pack: PackDef) -> Optional[Tuple[str, str, str]]:
    pid = PACK_ALIASES.get(pack.pack_id, pack.pack_id)
    return _EXPORT.get(pid)


def job_status(pack_id: str) -> Dict[str, Any]:
    with _LOCK:
        row = dict(_JOBS.get(pack_id) or {"status": "idle"})
    row.setdefault("pack_id", pack_id)
    return row


def tape_last_day(pack: PackDef) -> Optional[date]:
    from app.research.variant_ledger import _locked_rows

    days = []
    for row in _locked_rows(pack):
        raw = str(row.get("day") or "")[:10]
        if len(raw) == 10:
            try:
                days.append(date.fromisoformat(raw))
            except ValueError:
                continue
    return max(days) if days else None


def latest_closed_day(today: Optional[date] = None) -> date:
    """Last weekday session whose tape can be built. Today is closed after 15:30 IST; during cash hours use yesterday."""
    day = today or session_day()
    if market_session() in ("open", "pre"):
        day = day - timedelta(days=1)
    while day.weekday() >= 5:
        day = day - timedelta(days=1)
    return day


def _parse_iso_day(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _tape_synced_through(pack: PackDef) -> Optional[date]:
    nifty_root, bn_root = _roots()
    spec = _spec(pack)
    if spec is None:
        return None
    lab = nifty_root if spec[0] == "nifty" else bn_root
    path = lab / spec[2]
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return _parse_iso_day(raw.get("synced_through"))


def tape_cover_day(pack: PackDef) -> Optional[date]:
    """Last calendar day already covered: last trade or last successful sync-through, whichever is later."""
    last = tape_last_day(pack)
    synced = _tape_synced_through(pack)
    if last and synced:
        return max(last, synced)
    return synced or last


def _has_weekday(start: date, end: date) -> bool:
    day = start
    while day <= end:
        if day.weekday() < 5:
            return True
        day += timedelta(days=1)
    return False


def clamp_sync_to(requested: Optional[str], sync_from: date, sync_to_max: date) -> Optional[date]:
    if not requested:
        return sync_to_max
    try:
        want = date.fromisoformat(str(requested)[:10])
    except ValueError:
        return None
    if want < sync_from or want > sync_to_max:
        return None
    return want


def tape_net_to_last(pack: PackDef) -> float:
    from app.research.variant_ledger import _closed_net, _locked_rows

    nets = [_closed_net(row) for row in _locked_rows(pack)]
    return round(sum(n for n in nets if n is not None), 2)


def sync_window(pack: PackDef) -> Dict[str, Any]:
    paper = books.paper_book_start()
    sync_to = latest_closed_day()
    last = tape_last_day(pack)
    cover = tape_cover_day(pack)
    sync_from = LOCKED_START if cover is None else cover + timedelta(days=1)
    can = sync_from <= sync_to and _has_weekday(sync_from, sync_to)
    spec = _spec(pack)
    job = job_status(pack.pack_id)
    session = market_session()
    return {
        "tape_exists": last is not None,
        "tape_last_day": last.isoformat() if last else None,
        "tape_net_pnl": tape_net_to_last(pack) if last else 0.0,
        "paper_start": paper.isoformat(),
        "sync_from": sync_from.isoformat() if can else None,
        "sync_to": sync_to.isoformat() if can else None,
        "can_sync": bool(can and spec is not None),
        "today_open": session in ("open", "pre"),
        "sync_status": job.get("status") or "idle",
        "sync_detail": job.get("detail"),
    }


def start_sync(pack_id: str, to_day: Optional[str] = None) -> Dict[str, Any]:
    pack = paper_pack(pack_id)
    if pack is None:
        return {"ok": False, "error": "unknown_pack", "pack_id": pack_id}
    spec = _spec(pack)
    if spec is None:
        return {"ok": False, "error": "no_recipe", "pack_id": pack.pack_id}
    window = sync_window(pack)
    if window.get("sync_status") == "running":
        return {"ok": True, "started": False, "pack_id": pack.pack_id, **window}
    if not window.get("can_sync") or not window.get("sync_from") or not window.get("sync_to"):
        return {"ok": True, "started": False, "error": "up_to_date", "pack_id": pack.pack_id, **window}
    sync_from = date.fromisoformat(str(window["sync_from"]))
    sync_to_max = date.fromisoformat(str(window["sync_to"]))
    want = clamp_sync_to(to_day, sync_from, sync_to_max)
    if want is None:
        err = "already_synced" if to_day and str(to_day)[:10] <= str(window.get("tape_last_day") or "") else "date_not_closed"
        return {"ok": False, "started": False, "error": err, "pack_id": pack.pack_id, **window}
    with _LOCK:
        _JOBS[pack.pack_id] = {
            "status": "running",
            "detail": f"{sync_from.isoformat()} → {want.isoformat()}",
            "pack_id": pack.pack_id,
        }
    threading.Thread(
        target=_run,
        args=(pack.pack_id, spec, sync_from.isoformat(), want.isoformat()),
        daemon=True,
        name=f"tape-sync-{pack.pack_id}",
    ).start()
    return {
        "ok": True,
        "started": True,
        "pack_id": pack.pack_id,
        **window,
        "sync_from": sync_from.isoformat(),
        "sync_to": want.isoformat(),
    }


def merge_tapes(existing: Dict[str, Any], incoming: Dict[str, Any]) -> int:
    trades = list(existing.get("trades") or [])
    seen = {_trade_key(t) for t in trades}
    added = 0
    for row in incoming.get("trades") or []:
        key = _trade_key(row)
        if key in seen:
            continue
        seen.add(key)
        trades.append(row)
        added += 1
    trades.sort(key=lambda t: str(t.get("day") or ""))
    existing["trades"] = trades
    by_ym = {str(m.get("ym")): dict(m) for m in existing.get("months") or [] if isinstance(m, dict) and m.get("ym")}
    for month in incoming.get("months") or []:
        if not isinstance(month, dict) or not month.get("ym"):
            continue
        ym = str(month["ym"])
        if ym not in by_ym:
            by_ym[ym] = dict(month)
    month_net: Dict[str, float] = {}
    for row in trades:
        ym = str(row.get("day") or "")[:7]
        if len(ym) != 7:
            continue
        try:
            month_net[ym] = month_net.get(ym, 0.0) + float(row.get("net_pnl") or 0)
        except (TypeError, ValueError):
            continue
    for ym, net_m in month_net.items():
        row = by_ym.get(ym) or {"ym": ym}
        row["net_pnl"] = round(net_m, 2)
        by_ym[ym] = row
    existing["months"] = [by_ym[k] for k in sorted(by_ym)]
    net = sum(float(t.get("net_pnl") or 0) for t in trades)
    inv = dict(existing.get("investor") or incoming.get("investor") or {})
    locked_dd = inv.get("locked_peak_dd_pct") or inv.get("peak_dd_pct")
    inv["n_trades"] = len(trades)
    inv["net_pnl"] = round(net, 2)
    from app.research.stable import INITIAL_CAPITAL

    if locked_dd is not None:
        inv["locked_peak_dd_pct"] = locked_dd
        inv["peak_dd_pct"] = locked_dd
    inv["return_pct"] = round((net / INITIAL_CAPITAL) * 100.0, 2) if INITIAL_CAPITAL else 0.0
    existing["investor"] = inv
    if "recipe" not in existing and incoming.get("recipe"):
        existing["recipe"] = incoming["recipe"]
    return added


def _trade_key(row: Dict[str, Any]) -> Tuple[str, str, str, float]:
    try:
        net = round(float(row.get("net_pnl") or 0), 2)
    except (TypeError, ValueError):
        net = 0.0
    return (
        str(row.get("day") or "")[:10],
        str(row.get("symbol") or ""),
        str(row.get("sleeve") or ""),
        net,
    )


def _roots() -> Tuple[Path, Path]:
    from app.auth import get_settings

    s = get_settings()
    return s.nifty_lab_root, s.bn_lab_root


def _lab_python(lab_root: Path) -> str:
    for cand in (
        lab_root / ".venv" / "Scripts" / "python.exe",
        lab_root / ".venv" / "bin" / "python3",
        Path("/root/Options-Edge-Lab/.venv/bin/python3"),
        Path("/root/Options-Nifty-Edge-Lab/.venv/bin/python3"),
    ):
        if cand.exists():
            return str(cand)
    return sys.executable


def _run(pack_id: str, spec: Tuple[str, str, str], date_from: str, date_to: str) -> None:
    lab_kind, recipe, tape_rel = spec
    nifty_root, bn_root = _roots()
    lab = nifty_root if lab_kind == "nifty" else bn_root
    script = lab / "scripts" / (
        "export_nifty_trade_tape.py" if lab_kind == "nifty" else "export_bn_trade_tape.py"
    )
    dest = lab / tape_rel
    lake = lab / "data_lake"
    try:
        if not script.is_file():
            raise FileNotFoundError(f"export script missing: {script}")
        if not lake.is_dir():
            raise FileNotFoundError(f"data lake missing: {lake}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            out_json = Path(tmp) / "gap.json"
            out_csv = Path(tmp) / "gap.csv"
            env = {**os.environ, "DATA_LAKE_ROOT": str(lake)}
            proc = subprocess.run(
                [
                    _lab_python(lab),
                    str(script),
                    "--recipe",
                    recipe,
                    "--from",
                    date_from,
                    "--to",
                    date_to,
                    "--out-json",
                    str(out_json),
                    "--out-csv",
                    str(out_csv),
                ],
                cwd=str(lab),
                capture_output=True,
                text=True,
                timeout=2400,
                env=env,
            )
            if proc.returncode != 0:
                tail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-400:]
                raise RuntimeError(tail or f"exit {proc.returncode}")
            incoming = json.loads(out_json.read_text(encoding="utf-8")) if out_json.is_file() else {}
        existing: Dict[str, Any] = {"trades": [], "months": [], "investor": {}}
        if dest.is_file():
            existing = json.loads(dest.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {"trades": [], "months": [], "investor": {}}
        added = merge_tapes(existing, incoming if isinstance(incoming, dict) else {})
        existing["synced_through"] = date_to
        tmp_dest = dest.with_name(dest.name + ".tmp")
        tmp_dest.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        tmp_dest.replace(dest)
        with _LOCK:
            _JOBS[pack_id] = {
                "status": "done",
                "detail": (
                    f"added {added} trades {date_from} → {date_to}"
                    if added
                    else f"no new trades in lake {date_from} → {date_to}"
                ),
                "added": added,
                "pack_id": pack_id,
            }
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            _JOBS[pack_id] = {
                "status": "error",
                "detail": str(exc)[:400],
                "pack_id": pack_id,
            }
