"""Promote lab shadow ok cards → desk_paper fills so Trades/Book match client paper."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.books.adapters import BookPaths, paper_book_start, _num
from app.books import shadow_oms
from app.session import session_day


def _default_lot_size(und: str) -> int:
    return 30 if und == "BANKNIFTY" else 65


def _qty_lots(lab: dict, exe: dict, und: str) -> tuple[int, int, int]:
    lot_size = int(lab.get("lot_size") or 0) or _default_lot_size(und)
    qty = int(lab.get("qty") or 0)
    lots = int(exe.get("lots") or lab.get("lots") or 0)
    if qty <= 0 and lots > 0:
        qty = lots * lot_size
    if lots <= 0 and qty > 0 and lot_size > 0:
        lots = max(1, qty // lot_size)
    if qty <= 0:
        qty = lot_size
        lots = 1
    return qty, lots, lot_size


def promote_day(book: BookPaths, day: str, *, force: bool = False) -> Dict[str, Any]:
    """
    For each lab status=ok row with entry: write broker_fill source=desk_paper
    if missing (or force). Closed when lab has exit; else entry-only open.
    """
    path = book.shadow_dir / f"shadow_{day}.jsonl"
    if not path.exists():
        return {"day": day, "underlying": book.name, "promoted": 0, "skipped": 0, "rows": []}
    rows = shadow_oms._load_rows(path)  # noqa: SLF001 — shared journal IO
    promoted = 0
    skipped = 0
    details: List[dict] = []
    changed = False
    for row in rows:
        lab = row.get("lab") if isinstance(row.get("lab"), dict) else {}
        exe = row.get("execution") if isinstance(row.get("execution"), dict) else {}
        if str(lab.get("status") or "") != "ok":
            skipped += 1
            continue
        entry = _num(lab.get("entry"))
        if entry is None or entry <= 0:
            skipped += 1
            continue
        existing = row.get("broker_fill") if isinstance(row.get("broker_fill"), dict) else None
        if existing and not force:
            src = str(existing.get("source") or "").lower()
            if src in ("desk_paper", "paper", "live", "dhan_tradebook", "manual") or existing.get("entry") is not None:
                skipped += 1
                continue
        exit_px = _num(lab.get("exit"))
        net = _num(lab.get("net_pnl"))
        exit_reason = str(lab.get("exit_reason") or "")
        qty, lots, lot_size = _qty_lots(lab, exe, book.name)
        sleeve = str(row.get("sleeve") or "fade").lower()
        client_oid = f"lab2paper-{book.name.lower()}-{sleeve}-{day}"
        broker_oid = f"paper_{uuid4().hex[:10]}"
        # Closed lab cards (eod/stop/tp) → full fill; otherwise entry-only open.
        closed = exit_px is not None and exit_reason not in ("", "open")
        fill = {
            "entry": float(entry),
            "exit": float(exit_px) if closed else None,
            "net_pnl": round(float(net), 2) if closed and net is not None else None,
            "notes": "lab_promoted_to_desk_paper",
            "source": "desk_paper",
            "recorded_at": shadow_oms._now(),  # noqa: SLF001
            "qty": qty,
            "exit_reason": exit_reason if closed else "open",
        }
        row["broker_fill"] = fill
        row["broker_order"] = {
            "client_order_id": client_oid,
            "broker_order_id": broker_oid,
            "security_id": lab.get("security_id"),
            "symbol": lab.get("symbol"),
            "side": "BUY",
            "lots": lots,
            "quantity": qty,
            "lot_size": lot_size,
            "mode": "paper",
            "state": "TRADED",
            "placed_at": fill["recorded_at"],
            "underlying": book.name,
            "source": "lab_promote",
        }
        row["tradeable"] = True
        promoted += 1
        changed = True
        details.append(
            {
                "sleeve": sleeve,
                "entry": fill["entry"],
                "exit": fill["exit"],
                "net_pnl": fill["net_pnl"],
                "qty": qty,
                "lots": lots,
            }
        )
    if changed:
        shadow_oms._save_rows(path, rows)  # noqa: SLF001
        try:
            from app.books.adapters import ensure_lab_on_path

            ensure_lab_on_path(book.lab_root)
            from edge_lab.risk.execution_brakes import (  # type: ignore
                load_book_config,
                rebuild_state_from_shadow,
                save_state,
            )

            cfg = load_book_config(book.config_path)
            state = rebuild_state_from_shadow(book.shadow_dir, cfg, prefer_broker=True)
            save_state(book.state_path, state)
        except Exception as exc:  # noqa: BLE001
            return {
                "day": day,
                "underlying": book.name,
                "promoted": promoted,
                "skipped": skipped,
                "rows": details,
                "rebuild_error": str(exc)[:200],
            }
    return {
        "day": day,
        "underlying": book.name,
        "promoted": promoted,
        "skipped": skipped,
        "rows": details,
    }


def promote_range(
    books: List[BookPaths],
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    force: bool = False,
) -> Dict[str, Any]:
    start = start or paper_book_start()
    end = end or session_day()
    out: List[dict] = []
    total = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            for b in books:
                rec = promote_day(b, d.isoformat(), force=force)
                total += int(rec.get("promoted") or 0)
                if rec.get("promoted"):
                    out.append(rec)
        d += timedelta(days=1)
    return {"from": start.isoformat(), "to": end.isoformat(), "promoted_total": total, "days": out}
