"""Conflated mark.batch for /ws/desk — mock ledger + Dhan feed cache.

Does not bump RUNNER.seq. UI applies marks in memory; snapshot is a safety net.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from app.desk_events import emit_mark_batch, position_key
from app.runners.state import RUNNER
from app.ws_hub import HUB

_rows: Dict[str, Dict[str, Any]] = {}
_last_books: List[Dict[str, Any]] = []
_realized: float = 0.0
_spot_prev: Dict[str, float] = {}
_last_fp: Optional[str] = None
_dirty: bool = True
_lock_note = threading.Lock()


def mark_dirty() -> None:
    global _dirty
    _dirty = True


def note_depth(_depth: Any = None) -> None:
    mark_dirty()


def tracked_security_ids() -> List[str]:
    with _lock_note:
        return [
            str(r["security_id"])
            for r in _rows.values()
            if r.get("security_id") and str(r.get("security_id")).strip()
        ]


def note_position(row: Dict[str, Any]) -> None:
    key = position_key(row)
    if not key:
        return
    qty = int(row.get("qty") or row.get("quantity") or 0)
    with _lock_note:
        if qty == 0:
            _rows.pop(key, None)
        else:
            _rows[key] = dict(row)
        global _dirty
        _dirty = True


def drop_position(row_or_key: Any) -> None:
    if isinstance(row_or_key, dict):
        key = position_key(row_or_key)
    else:
        key = str(row_or_key or "")
    if not key:
        return
    with _lock_note:
        _rows.pop(key, None)
        global _dirty
        _dirty = True


def sync_rows(rows: List[Dict[str, Any]]) -> None:
    with _lock_note:
        _rows.clear()
        for row in rows:
            if int(row.get("qty") or row.get("quantity") or 0) == 0:
                continue
            key = position_key(row)
            if key:
                _rows[key] = dict(row)
        global _dirty
        _dirty = True


def remember_health(payload: Dict[str, Any]) -> None:
    """Keep realized / books from the slower health.tick REST snapshot."""
    global _realized, _last_books
    if payload.get("realized_pnl_today") is not None:
        try:
            _realized = float(payload["realized_pnl_today"])
        except (TypeError, ValueError):
            pass
    books = payload.get("books")
    if isinstance(books, list) and books:
        _last_books = [dict(b) for b in books if isinstance(b, dict)]
    rows = payload.get("position_rows")
    if isinstance(rows, list):
        sync_rows(rows)
    _seed_prev_close("NIFTY", payload.get("nifty_spot"), payload.get("nifty_change_pct"))
    _seed_prev_close("BANKNIFTY", payload.get("banknifty_spot"), payload.get("banknifty_change_pct"))


def _seed_prev_close(und: str, ltp: Any, pct: Any) -> None:
    """Anchor live-feed % to REST prev-close (Groww-style), not first tick."""
    try:
        px = float(ltp) if ltp is not None else None
        ch = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        return
    if px is None or ch is None or px <= 0:
        return
    denom = 1.0 + ch / 100.0
    if denom == 0:
        return
    _spot_prev[und] = px / denom


def _fp(payload: Dict[str, Any]) -> str:
    marks = payload.get("marks") or []
    bits = [
        str(payload.get("nifty_spot")),
        str(payload.get("banknifty_spot")),
        str(payload.get("unrealized_pnl")),
        str(payload.get("today_net")),
    ]
    for m in marks:
        bits.append(f"{m.get('key')}:{m.get('ltp')}:{m.get('unrealized_pnl')}")
    return "|".join(bits)


def _emit(payload: Dict[str, Any]) -> bool:
    global _last_fp, _dirty
    if not payload or not HUB.has_clients():
        _dirty = False
        return False
    fp = _fp(payload)
    if fp == _last_fp:
        _dirty = False
        return False
    _last_fp = fp
    _dirty = False
    emit_mark_batch(payload)
    return True


def _change_pts(und: str, ltp: Optional[float]) -> Optional[float]:
    if ltp is None:
        return None
    prev = _spot_prev.get(und)
    if prev is None or prev <= 0:
        return None
    return round(float(ltp) - prev, 2)


def _change_pct(und: str, ltp: Optional[float]) -> Optional[float]:
    if ltp is None:
        return None
    prev = _spot_prev.get(und)
    if prev is None or prev <= 0:
        return None
    return round(100.0 * (float(ltp) - prev) / prev, 4)


def _books_with_mtm(mtm_by_und: Dict[str, float]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for book in _last_books:
        b = dict(book)
        und = str(b.get("underlying") or "")
        mtm = round(float(mtm_by_und.get(und) or 0), 2)
        cap = float(b.get("capital") or 0)
        prev_eq = float(b.get("equity") if b.get("equity") is not None else cap)
        prev_mtm = float(b.get("open_mtm") or 0)
        realized_part = prev_eq - prev_mtm
        b["open_mtm"] = mtm
        b["equity"] = round(realized_part + mtm, 2)
        out.append(b)
    return out


def build_mock_batch() -> Dict[str, Any]:
    """Caller must hold the mock ledger lock."""
    from app.mock import MOCK

    spots = MOCK.spots()
    rows = MOCK.ledger.position_rows()
    marks: List[Dict[str, Any]] = []
    mtm_by: Dict[str, float] = {"NIFTY": 0.0, "BANKNIFTY": 0.0}
    for row in rows:
        key = position_key(row)
        ltp = row.get("ltp")
        pnl = float(row.get("unrealized_pnl") or 0)
        und = str(row.get("underlying") or "")
        if und in mtm_by:
            mtm_by[und] += pnl
        if not key or ltp is None:
            continue
        marks.append(
            {
                "key": key,
                "ltp": round(float(ltp), 4),
                "unrealized_pnl": round(pnl, 2),
            }
        )
    n = spots.get("NIFTY") or {}
    b = spots.get("BANKNIFTY") or {}
    unreal = MOCK.ledger.unrealized_sum()
    real = MOCK.ledger.realized_sum()
    books = MOCK.books_snapshot()
    global _last_books, _realized
    _last_books = [dict(x) for x in books]
    _realized = real
    return {
        "nifty_spot": n.get("ltp"),
        "nifty_change_pct": n.get("change_pct"),
        "nifty_change_pts": n.get("change_pts"),
        "banknifty_spot": b.get("ltp"),
        "banknifty_change_pct": b.get("change_pct"),
        "banknifty_change_pts": b.get("change_pts"),
        "unrealized_pnl": unreal,
        "realized_pnl_today": real,
        "today_net": round(real + unreal, 2),
        "open_positions": len(rows),
        "marks": marks,
        "books": books,
    }


def emit_mock_marks() -> bool:
    """Caller must hold the mock ledger lock."""
    return _emit(build_mock_batch())


def build_paper_batch() -> Dict[str, Any]:
    from app.brokers.dhan.client import BN_SECURITY_ID, NIFTY_SECURITY_ID
    from app.execution.dhan_ws_feed import get_depth

    # Prefer REST prev-close anchors when feed has no prior seed yet.
    if "NIFTY" not in _spot_prev or "BANKNIFTY" not in _spot_prev:
        try:
            from app.brokers.dhan import client as dhan

            pack = dhan.spots_with_change()
            for und in ("NIFTY", "BANKNIFTY"):
                row = pack.get(und) or {}
                _seed_prev_close(und, row.get("ltp"), row.get("change_pct"))
        except Exception:
            pass

    with _lock_note:
        rows = list(_rows.values())
    marks: List[Dict[str, Any]] = []
    mtm_by: Dict[str, float] = {"NIFTY": 0.0, "BANKNIFTY": 0.0}
    for row in rows:
        key = position_key(row)
        sid = str(row.get("security_id") or "")
        depth = get_depth(sid) if sid else None
        ltp = float(depth.ltp) if depth is not None else row.get("ltp")
        avg = float(row.get("average_price") or 0)
        qty = int(row.get("qty") or row.get("quantity") or 0)
        if ltp is None:
            pnl = float(row.get("unrealized_pnl") or 0)
        else:
            ltp = float(ltp)
            pnl = round((ltp - avg) * qty, 2)
        und = str(row.get("underlying") or "")
        if und in mtm_by:
            mtm_by[und] += pnl
        if not key:
            continue
        rec: Dict[str, Any] = {"key": key, "unrealized_pnl": round(float(pnl), 2)}
        if ltp is not None:
            rec["ltp"] = round(float(ltp), 4)
        marks.append(rec)

    nd = get_depth(NIFTY_SECURITY_ID)
    bd = get_depth(BN_SECURITY_ID)
    n_ltp = float(nd.ltp) if nd is not None else None
    b_ltp = float(bd.ltp) if bd is not None else None
    unreal = round(sum(mtm_by.values()), 2)
    books = _books_with_mtm(mtm_by)
    return {
        "nifty_spot": n_ltp,
        "nifty_change_pct": _change_pct("NIFTY", n_ltp),
        "nifty_change_pts": _change_pts("NIFTY", n_ltp),
        "banknifty_spot": b_ltp,
        "banknifty_change_pct": _change_pct("BANKNIFTY", b_ltp),
        "banknifty_change_pts": _change_pts("BANKNIFTY", b_ltp),
        "unrealized_pnl": unreal,
        "realized_pnl_today": _realized,
        "today_net": round(_realized + unreal, 2),
        "open_positions": len(rows),
        "marks": marks,
        "books": books,
    }


def flush_paper_marks() -> bool:
    mode = (RUNNER.mode or "").lower()
    if mode not in ("paper", "live"):
        return False
    if not _dirty and _last_fp is not None:
        return False
    return _emit(build_paper_batch())


def reset() -> None:
    global _last_fp, _dirty, _realized
    with _lock_note:
        _rows.clear()
        _last_books.clear()
        _spot_prev.clear()
        _last_fp = None
        _dirty = True
        _realized = 0.0
