"""Durable paper/live session archive on the desk host (VPS disk).

UI still uses the same trader routes. This module snapshots IST-day books so a
restart, mock overnight, or later review does not lose the session.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.session import session_day


def paper_dir() -> Path:
    path = Path(__file__).resolve().parents[1] / "data" / "paper"
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_path(day: Optional[str] = None) -> Path:
    return paper_dir() / f"{day or session_day().isoformat()}.json"


def load(day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    path = snapshot_path(day)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def capture(*, reason: str = "tick") -> Optional[Path]:
    """Write one JSON file for the IST session. Safe to call often (overwrite)."""
    from app.books import adapters as books
    from app.brokers.dhan import client as dhan
    from app.runners.state import RUNNER

    mode = (RUNNER.mode or "").lower()
    if mode not in ("paper", "live"):
        return None

    from app.auth import get_settings

    s = get_settings()
    book_list = [
        books.nifty_book(s.nifty_lab_root, s.nifty_config),
        books.bn_book(s.bn_lab_root, s.bn_config),
    ]
    day = session_day().isoformat()
    trades = books.trades_today(book_list, day)
    signals = books.signals_today(book_list, day)
    positions: Dict[str, Any] = {"rows": [], "row_count": 0}
    orders: Dict[str, Any] = {"orders": [], "count": 0}
    dhan_trades: list = []
    try:
        positions = dhan.positions_grid()
    except Exception as exc:  # noqa: BLE001
        positions = {"rows": [], "row_count": 0, "detail": str(exc)[:240]}
    try:
        orders = dhan.open_orders_response()
    except Exception as exc:  # noqa: BLE001
        orders = {"orders": [], "count": 0, "detail": str(exc)[:240]}
    try:
        dhan_trades = dhan.trade_book_today()
    except Exception:
        dhan_trades = []

    payload = {
        "day": day,
        "saved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "reason": reason,
        "mode": mode,
        "execution": RUNNER.execution,
        "positions": positions,
        "orders_open": orders,
        "trades": trades,
        "signals": signals,
        "dhan_trade_book": dhan_trades,
    }
    path = snapshot_path(day)
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")
    for book in book_list:
        src = book.shadow_dir / f"shadow_{day}.jsonl"
        if src.exists():
            dest = paper_dir() / f"shadow_{book.name}_{day}.jsonl"
            dest.write_bytes(src.read_bytes())
    return path
