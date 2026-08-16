"""Shadow journal write-back for desk paper/live orders (per Edge Lab book)."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app.books.adapters import BookPaths, ensure_lab_on_path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _journal_path(book: BookPaths, day: str) -> Path:
    book.shadow_dir.mkdir(parents=True, exist_ok=True)
    return book.shadow_dir / f"shadow_{day}.jsonl"


def _load_rows(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _save_rows(path: Path, rows: list) -> None:
    path.write_text(
        "\n".join(json.dumps(r, default=str) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _match_row(
    rows: list,
    *,
    sleeve: str,
    day: str,
    symbol: str = "",
    strike: Optional[float] = None,
) -> Optional[dict]:
    sleeve = sleeve.lower()
    for r in rows:
        if str(r.get("sleeve") or "").lower() != sleeve:
            continue
        lab = r.get("lab") or {}
        if str(lab.get("day") or day) != day:
            continue
        if lab.get("status") not in ("ok", None, "") and lab.get("status") != "ok":
            # allow attaching to ok only
            if lab.get("status") != "ok":
                continue
        if symbol and str(lab.get("symbol") or "").upper() not in ("", symbol.upper()):
            if str(lab.get("symbol") or "").upper() != symbol.upper():
                continue
        if strike is not None and lab.get("strike") not in (None, "", 0, 0.0):
            try:
                if abs(float(lab["strike"]) - float(strike)) > 0.01:
                    continue
            except (TypeError, ValueError):
                pass
        if lab.get("status") == "ok":
            return r
    # second pass: any ok sleeve/day
    for r in rows:
        if str(r.get("sleeve") or "").lower() != sleeve:
            continue
        lab = r.get("lab") or {}
        if str(lab.get("day") or day) == day and lab.get("status") == "ok":
            return r
    return None


def record_broker_order(
    book: BookPaths,
    *,
    day: str,
    sleeve: str,
    order: Dict[str, Any],
    contract: Dict[str, Any],
    create_if_missing: bool = True,
) -> Dict[str, Any]:
    """Attach broker_order to today's journal sleeve row (or create a desk row)."""
    path = _journal_path(book, day)
    rows = _load_rows(path)
    row = _match_row(
        rows,
        sleeve=sleeve,
        day=day,
        symbol=str(contract.get("tradingsymbol") or ""),
        strike=contract.get("strike"),
    )
    payload = {
        "client_order_id": order.get("client_order_id"),
        "broker_order_id": (order.get("broker") or {}).get("raw", {}).get("orderId")
        if isinstance(order.get("broker"), dict)
        else order.get("broker_order_id"),
        "security_id": contract.get("security_id"),
        "symbol": contract.get("tradingsymbol"),
        "side": order.get("side"),
        "lots": order.get("lots"),
        "quantity": order.get("quantity"),
        "lot_size": contract.get("lot_size"),
        "mode": order.get("mode"),
        "state": order.get("state"),
        "placed_at": _now(),
        "underlying": book.name,
    }
    if row is None and create_if_missing:
        row = {
            "ts": _now(),
            "sleeve": sleeve,
            "config": "desk_oms",
            "lab": {
                "day": day,
                "underlying": book.name,
                "side": contract.get("option_type") or "",
                "strike": contract.get("strike") or 0,
                "symbol": contract.get("tradingsymbol") or "",
                "qty": order.get("quantity") or 0,
                "status": "ok",
                "source": "desk_oms",
            },
            "broker_fill": None,
            "tradeable": True,
            "execution": {"allow": True, "reason": "desk_oms", "lots": order.get("lots")},
        }
        rows.append(row)
    if row is None:
        return {"ok": False, "reason": "no journal row"}
    row["broker_order"] = payload
    # keep security_id on lab for next cycle UI
    lab = row.setdefault("lab", {})
    lab["security_id"] = contract.get("security_id")
    lab["symbol"] = lab.get("symbol") or contract.get("tradingsymbol")
    lab["qty"] = order.get("quantity") or lab.get("qty")
    lab["lot_size"] = contract.get("lot_size")
    _save_rows(path, rows)
    return {"ok": True, "path": str(path), "broker_order": payload}


def record_entry_fill(
    book: BookPaths,
    *,
    day: str,
    sleeve: str,
    entry: float,
    qty: int,
    notes: str = "desk_paper_entry",
    source: str = "paper",
    net_pnl: Optional[float] = None,
    exit_px: Optional[float] = None,
) -> Dict[str, Any]:
    """Write broker_fill (entry, optional exit) and rebuild execution_state when exit known."""
    path = _journal_path(book, day)
    rows = _load_rows(path)
    row = _match_row(rows, sleeve=sleeve, day=day)
    if row is None:
        return {"ok": False, "reason": "no journal row for fill"}
    fill = {
        "entry": float(entry),
        "exit": None if exit_px is None else float(exit_px),
        "net_pnl": None if net_pnl is None else round(float(net_pnl), 2),
        "notes": notes,
        "source": source,
        "recorded_at": _now(),
        "qty": int(qty),
    }
    row["broker_fill"] = fill
    _save_rows(path, rows)

    rebuilt = False
    if exit_px is not None:
        try:
            ensure_lab_on_path(book.lab_root)
            from edge_lab.risk.execution_brakes import (  # type: ignore
                load_book_config,
                rebuild_state_from_shadow,
                save_state,
            )

            cfg = load_book_config(book.config_path)
            state = rebuild_state_from_shadow(book.shadow_dir, cfg, prefer_broker=True)
            save_state(book.state_path, state)
            rebuilt = True
        except Exception as exc:  # noqa: BLE001
            return {"ok": True, "fill": fill, "rebuilt": False, "rebuild_error": str(exc)}
    return {"ok": True, "fill": fill, "rebuilt": rebuilt, "path": str(path)}


def today_iso() -> str:
    return date.today().isoformat()
