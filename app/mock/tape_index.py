"""Index locked most_stable tapes by calendar day."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.brokers.dhan.contracts import DEFAULT_LOT
from app.research.stable import PACKS, _load_json, _pick_run
from app.session import IST

ENTRY_START = time(9, 30)
ENTRY_STEP_MIN = 8
ENTRY_CAP = time(14, 30)


def _roots():
    from app.auth import get_settings

    s = get_settings()
    return {"NIFTY": s.nifty_lab_root, "BANKNIFTY": s.bn_lab_root}


def _most_stable_packs():
    return [p for p in PACKS if p.selection == "most_stable"]


def _norm_opt(raw: Any) -> str:
    s = str(raw or "").upper()
    if s in ("CE", "CALL", "C"):
        return "CE"
    if s in ("PE", "PUT", "P"):
        return "PE"
    return "PE"


def load_tape_trades() -> List[Dict[str, Any]]:
    roots = _roots()
    out: List[Dict[str, Any]] = []
    for pack in _most_stable_packs():
        path = roots[pack.underlying] / pack.tape_rel
        if not path.exists():
            continue
        try:
            raw = _load_json(path)
            run = _pick_run(raw, pack.run_id)
        except Exception:
            continue
        for t in list(run.get("trades") or []):
            day = str(t.get("day") or "")
            if len(day) < 10:
                continue
            strike = float(t.get("strike") or 0)
            opt = _norm_opt(t.get("side") or t.get("option_type"))
            lots = int(t.get("actual_lots") or t.get("lots") or t.get("target_lots") or 1)
            lot_size = int(DEFAULT_LOT.get(pack.underlying, 65))
            entry = float(t.get("entry") or 0)
            exit_px = float(t.get("exit") or entry)
            reason = str(t.get("exit_reason") or ("take_profit" if t.get("is_tp") else "stop"))
            if reason in ("tp", "TP"):
                reason = "take_profit"
            sid = f"mock-{pack.underlying}-{int(strike)}-{opt}"
            out.append(
                {
                    "pack_id": pack.pack_id,
                    "underlying": pack.underlying,
                    "day": day[:10],
                    "sleeve": str(t.get("sleeve") or "fade").lower(),
                    "option_type": opt,
                    "strike": strike,
                    "symbol": str(t.get("symbol") or f"{pack.underlying}{int(strike)}{opt}"),
                    "lots": lots,
                    "lot_size": lot_size,
                    "entry": entry,
                    "exit": exit_px,
                    "exit_reason": reason,
                    "gap_pts": t.get("gap_pts"),
                    "net_pnl": float(t.get("net_pnl") or 0),
                    "is_tp": bool(t.get("is_tp") or reason == "take_profit"),
                    "is_stop": bool(t.get("is_stop") or reason == "stop"),
                    "security_id": sid,
                }
            )
    return out


def pick_demo_days(trades: List[Dict[str, Any]]) -> Tuple[str, Dict[str, str]]:
    """Return (replay_day, {underlying: source_day}). Prefer a day with TP and stop."""
    by_und: Dict[str, Dict[str, List[dict]]] = {"NIFTY": {}, "BANKNIFTY": {}}
    for t in trades:
        und = t["underlying"]
        by_und.setdefault(und, {})
        by_und[und].setdefault(t["day"], []).append(t)

    def score(day: str, rows: List[dict]) -> tuple:
        has_tp = any(r.get("is_tp") for r in rows)
        has_stop = any(r.get("is_stop") for r in rows)
        return (int(has_tp) + int(has_stop), len(rows), day)

    source: Dict[str, str] = {}
    for und, days in by_und.items():
        if not days:
            continue
        ranked = sorted((score(d, rows) for d, rows in days.items()), reverse=True)
        source[und] = ranked[0][2]
    replay = source.get("NIFTY") or source.get("BANKNIFTY") or date.today().isoformat()
    return replay, source


def schedule_for_replay(
    trades: List[Dict[str, Any]],
    *,
    replay_day: str,
    source_days: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Map each book's chosen source day onto one sim calendar date."""
    day_d = date.fromisoformat(replay_day)
    selected: List[Dict[str, Any]] = []
    for und, src in source_days.items():
        rows = [t for t in trades if t["underlying"] == und and t["day"] == src]
        rows.sort(key=lambda r: (r.get("sleeve"), r.get("strike")))
        for i, t in enumerate(rows):
            entry_t = _entry_time(i)
            exit_t = _exit_time(entry_t, bool(t.get("is_tp")))
            expiry = replay_day
            ev = dict(t)
            ev["replay_day"] = replay_day
            ev["source_day"] = src
            ev["idx"] = i
            ev["signal_id"] = f"{und.lower()}-{ev['sleeve']}-{replay_day}-{i + 1}"
            ev["entry_at"] = datetime.combine(day_d, entry_t, tzinfo=IST)
            ev["exit_at"] = datetime.combine(day_d, exit_t, tzinfo=IST)
            ev["expiry"] = expiry
            ev["skip_at"] = ev["entry_at"] + timedelta(minutes=ENTRY_STEP_MIN)
            selected.append(ev)
    selected.sort(key=lambda r: r["entry_at"])
    return selected


def _entry_time(i: int) -> time:
    base = datetime.combine(date(2000, 1, 1), ENTRY_START) + timedelta(minutes=i * ENTRY_STEP_MIN)
    cap = datetime.combine(date(2000, 1, 1), ENTRY_CAP)
    if base > cap:
        base = cap
    return base.time().replace(microsecond=0)


def _exit_time(entry: time, is_tp: bool) -> time:
    start = datetime.combine(date(2000, 1, 1), entry)
    close = datetime.combine(date(2000, 1, 1), time(15, 20))
    frac = 0.35 if is_tp else 0.65
    end = start + timedelta(seconds=(close - start).total_seconds() * frac)
    if end <= start:
        end = start + timedelta(minutes=20)
    if end > close:
        end = close
    return end.time().replace(microsecond=0)
