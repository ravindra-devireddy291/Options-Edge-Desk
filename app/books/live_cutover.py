"""Per-book live cutover: Dhan place only when live flags + G5 fills ≥ target."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.auth import get_settings
from app.books.adapters import BookPaths, _row_matches_book

G5_TARGET = 20
# Desk paper OMS fills count toward G5 (same bar as real paper/live fills).
G5_SOURCES = {
    "dhan_tradebook",
    "paper",
    "live",
    "manual",
    "desk_paper",
}


def _fill_source(bf: Optional[dict]) -> str:
    if not bf:
        return ""
    return str(bf.get("source") or bf.get("notes") or "unknown").lower()


def is_g5_fill(bf: Optional[dict]) -> bool:
    """Only desk/live/dhan fills count. Lab tape with entry+exit must not unlock live."""
    if not bf or not isinstance(bf, dict):
        return False
    notes = str(bf.get("notes") or "").lower()
    src = _fill_source(bf)
    blob = f"{src} {notes}"
    if "virtual" in blob:
        return False
    if src in G5_SOURCES:
        return True
    return "desk_paper" in blob or "dhan_tradebook" in blob


def g5_sessions(book: BookPaths) -> int:
    """Count IST session days with at least one G5-counting broker_fill."""
    shadow = book.shadow_dir
    if not shadow.exists():
        return 0
    days = 0
    for path in sorted(shadow.glob("shadow_*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        hit = False
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not _row_matches_book(row, book):
                continue
            if is_g5_fill(row.get("broker_fill") if isinstance(row.get("broker_fill"), dict) else None):
                hit = True
                break
        if hit:
            days += 1
    return days


def g5_status(book: BookPaths) -> Dict[str, Any]:
    n = g5_sessions(book)
    return {
        "underlying": book.name,
        "g5_fills": n,
        "g5_target": G5_TARGET,
        "g5_pass": n >= G5_TARGET,
        "remaining": max(0, G5_TARGET - n),
    }


def book_live_flag(und: str) -> bool:
    """Master switch only. DESK_LIVE_ENABLED=0 keeps every book on paper."""
    if und not in ("NIFTY", "BANKNIFTY"):
        return False
    return bool(get_settings().live_enabled)


def book_uses_dhan(und: str, book: Optional[BookPaths] = None) -> bool:
    """
    True → place/cancel/positions for this book go to Dhan.
    False → desk paper OMS (simulate fill @ live LTP, no money).
    Requires DESK_LIVE_ENABLED=1 and G5 ≥ 20. LIVE_{UND} does not gate this.
    """
    s = get_settings()
    if not s.live_enabled:
        return False
    if not book_live_flag(und):
        return False
    if book is None:
        return False
    return g5_sessions(book) >= G5_TARGET


def any_book_live(books: list) -> bool:
    return any(book_uses_dhan(b.name, b) for b in books)


def cutover_snapshot(books: list) -> Dict[str, Any]:
    s = get_settings()
    rows = []
    for b in books:
        g5 = g5_status(b)
        live = book_uses_dhan(b.name, b)
        rows.append(
            {
                **g5,
                "live_flag": book_live_flag(b.name),
                "desk_live_enabled": bool(s.live_enabled),
                "uses_dhan": live,
                "oms": "dhan" if live else "paper",
            }
        )
    return {"books": rows, "g5_target": G5_TARGET}
