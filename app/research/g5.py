"""Read-only G5_TRACKER.json loaders for desk UI readiness meter."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.books.adapters import BookPaths

SESSIONS_CAP = 40


def _now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def tracker_path(book: BookPaths) -> Path:
    return book.shadow_dir / "G5_TRACKER.json"


def _normalize_book(book: BookPaths, raw: Dict[str, Any], *, sessions_cap: int = SESSIONS_CAP) -> Dict[str, Any]:
    sessions = raw.get("sessions") if isinstance(raw.get("sessions"), list) else []
    truncated = len(sessions) > sessions_cap
    if truncated:
        sessions = sessions[-sessions_cap:]
    out: Dict[str, Any] = {
        "underlying": book.name,
        "config": raw.get("config"),
        "updated": raw.get("updated"),
        "gate_G5": raw.get("gate_G5") if isinstance(raw.get("gate_G5"), dict) else {},
        "lab_coverage": raw.get("lab_coverage") if isinstance(raw.get("lab_coverage"), dict) else {},
        "slippage_vs_lab": raw.get("slippage_vs_lab") if isinstance(raw.get("slippage_vs_lab"), dict) else {},
        "sessions": sessions,
    }
    if truncated:
        out["sessions_truncated"] = True
        out["sessions_cap"] = sessions_cap
    return out


def _empty_book(book: BookPaths, error: str) -> Dict[str, Any]:
    return {
        "underlying": book.name,
        "config": None,
        "updated": None,
        "gate_G5": None,
        "lab_coverage": {},
        "slippage_vs_lab": {},
        "sessions": [],
        "error": error,
    }


def load_book_tracker(book: BookPaths, *, sessions_cap: int = SESSIONS_CAP) -> tuple[Dict[str, Any], Optional[str]]:
    """Return (book_row, error_or_None). Never raises."""
    path = tracker_path(book)
    if not path.exists():
        err = f"{book.name}:G5_TRACKER.json missing"
        return _empty_book(book, err), err
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        err = f"{book.name}:G5_TRACKER.json read_error:{exc}"
        return _empty_book(book, err), err
    if not isinstance(raw, dict):
        err = f"{book.name}:G5_TRACKER.json invalid_shape"
        return _empty_book(book, err), err
    return _normalize_book(book, raw, sessions_cap=sessions_cap), None


def g5_payload(
    books: Sequence[BookPaths],
    *,
    underlying: Optional[str] = None,
    sessions_cap: int = SESSIONS_CAP,
) -> Dict[str, Any]:
    """Normalized tracker(s) for UI. Soft-fail missing files; ok envelope stays true."""
    want = (underlying or "").strip().upper() or None
    if want and want not in ("NIFTY", "BANKNIFTY"):
        return {
            "updated": _now_z(),
            "books": [],
            "errors": [f"invalid_underlying:{want}"],
        }
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    latest: Optional[str] = None
    for book in books:
        if want and book.name != want:
            continue
        row, err = load_book_tracker(book, sessions_cap=sessions_cap)
        rows.append(row)
        if err:
            errors.append(err)
        elif row.get("updated"):
            u = str(row["updated"])
            if latest is None or u > latest:
                latest = u
    return {
        "updated": latest or _now_z(),
        "books": rows,
        "errors": errors,
    }
