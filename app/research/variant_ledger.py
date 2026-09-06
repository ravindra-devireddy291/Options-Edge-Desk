"""Per-variant trade ledger: locked 60m tape or paper/live journals. Same row shape as blotter."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.books import adapters as books
from app.research.stable import (
    INITIAL_CAPITAL,
    PackDef,
    SPAN,
    load_paper_variant,
    paper_pack,
    variant_label,
    yaml_allocation,
)
from app.session import session_day

CSV_FIELDS = (
    "day",
    "symbol",
    "underlying",
    "variant",
    "sleeve",
    "side",
    "lots",
    "qty",
    "entry_price",
    "exit_price",
    "net_pnl",
    "costs",
    "exit_reason",
    "mode",
    "pack_id",
)


def _roots() -> Tuple[Path, Path]:
    from app.auth import get_settings

    s = get_settings()
    return s.nifty_lab_root, s.bn_lab_root


def _pack_book(pack: PackDef) -> books.BookPaths:
    nifty_root, bn_root = _roots()
    root = nifty_root if pack.underlying == "NIFTY" else bn_root
    name = str(yaml_allocation(root / pack.config_rel).get("name") or pack.pack_id)
    return books.BookPaths(
        name=pack.underlying,
        lab_root=root,
        config_rel=pack.config_rel,
        shadow_dir=root / "reports" / "shadow",
        pack_id=pack.pack_id,
        variant=pack.selection if pack.selection in ("primary", "secondary") else "",
        config_name=name,
    )


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_day(raw: Optional[str], fallback: date) -> date:
    if not raw:
        return fallback
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return fallback


def _normalize_locked(raw: Dict[str, Any], pack: PackDef, index: int) -> Dict[str, Any]:
    day = str(raw.get("day") or "")[:10]
    lots = int(_num(raw.get("actual_lots") or raw.get("lots") or raw.get("target_lots")) or 0)
    qty = int(_num(raw.get("qty")) or 0)
    lot_size = int(qty / lots) if lots and qty else 0
    opt = str(raw.get("side") or raw.get("option_type") or "").upper()
    side = opt if opt in ("BUY", "SELL") else "BUY"
    option_type = opt if opt in ("CE", "PE") else None
    net = _num(raw.get("net_pnl"))
    costs = _num(raw.get("costs_inr") or raw.get("costs"))
    return {
        "trade_id": f"{pack.pack_id}:{day}:{index}",
        "underlying": pack.underlying,
        "pack_id": pack.pack_id,
        "variant": pack.selection if pack.selection in ("primary", "secondary") else None,
        "mode": "locked",
        "sleeve": str(raw.get("sleeve") or "fade").lower(),
        "symbol": str(raw.get("symbol") or ""),
        "side": side,
        "option_type": option_type,
        "qty": qty,
        "lots": lots,
        "lot_size": lot_size,
        "entry_price": _num(raw.get("entry") or raw.get("entry_price")),
        "exit_price": _num(raw.get("exit") or raw.get("exit_price")),
        "exit_reason": str(raw.get("exit_reason") or ""),
        "realized_pnl": net,
        "costs": costs,
        "net_pnl": net,
        "lab_entry": _num(raw.get("entry")),
        "broker_entry": None,
        "lab_exit": _num(raw.get("exit")),
        "broker_exit": None,
        "slip_entry": None,
        "slip_exit": None,
        "closed_at": f"{day}T10:00:00Z" if day else None,
        "day": day,
    }


def _locked_rows(pack: PackDef) -> List[Dict[str, Any]]:
    nifty_root, bn_root = _roots()
    root = nifty_root if pack.underlying == "NIFTY" else bn_root
    tape = (pack.tape_rel or "").strip()
    if not tape:
        return []
    path = root / tape
    if not path.is_file():
        return []
    from app.research.stable import _load_json, _pick_run

    raw = _load_json(path)
    run = _pick_run(raw, pack.run_id)
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(list(run.get("trades") or [])):
        if not isinstance(row, dict):
            continue
        out.append(_normalize_locked(row, pack, i))
    return out


def _paper_rows(pack: PackDef, start: date, end: date) -> List[Dict[str, Any]]:
    book = _pack_book(pack)
    out: List[Dict[str, Any]] = []
    day = start
    while day <= end:
        out.extend(books.trades_for_book(book, day.isoformat()))
        day += timedelta(days=1)
    return out


def _filter_days(rows: List[Dict[str, Any]], start: date, end: date) -> List[Dict[str, Any]]:
    keep: List[Dict[str, Any]] = []
    for row in rows:
        raw = str(row.get("day") or (row.get("closed_at") or "")[:10])
        if not raw:
            keep.append(row)
            continue
        try:
            d = date.fromisoformat(raw[:10])
        except ValueError:
            keep.append(row)
            continue
        if start <= d <= end:
            keep.append(row)
    return keep


def _closed_net(row: Dict[str, Any]) -> Optional[float]:
    if str(row.get("exit_reason") or "") in ("open", ""):
        return None
    return _num(row.get("net_pnl"))


def _stats(rows: List[Dict[str, Any]], capital: float) -> Dict[str, Any]:
    nets = [n for n in (_closed_net(r) for r in rows) if n is not None]
    n = len(nets)
    net = round(sum(nets), 2) if nets else 0.0
    wins = sum(1 for v in nets if v > 0)
    equity = capital
    peak = capital
    max_dd = 0.0
    by_day: Dict[str, float] = {}
    for row in rows:
        n_val = _closed_net(row)
        if n_val is None:
            continue
        day = str(row.get("day") or "")[:10]
        by_day[day] = by_day.get(day, 0.0) + n_val
    for day in sorted(by_day):
        equity += by_day[day]
        if equity > peak:
            peak = equity
        max_dd = max(max_dd, peak - equity)
    dd_pct = (max_dd / capital * 100.0) if capital > 0 else 0.0
    return {
        "n_trades": n,
        "net_pnl": net,
        "win_rate": (wins / n) if n else None,
        "dd_inr": round(max_dd, 2),
        "dd_pct": round(dd_pct, 2),
        "return_pct": round((net / capital) * 100.0, 2) if capital else 0.0,
    }


def variant_trades(
    *,
    pack_id: str,
    source: str = "locked",
    from_day: Optional[str] = None,
    to_day: Optional[str] = None,
) -> Dict[str, Any]:
    pack = paper_pack(pack_id)
    if pack is None:
        return {
            "error": "unknown_pack",
            "pack_id": pack_id,
            "trades": [],
            "trade_count": 0,
        }
    src = (source or "locked").strip().lower()
    if src == "live":
        src = "paper"
        live_requested = True
    else:
        live_requested = False
    today = session_day()
    if src == "paper":
        start = _parse_day(from_day, books.paper_book_start())
        end = _parse_day(to_day, today)
        if end < start:
            start, end = end, start
        rows = _paper_rows(pack, start, end)
        if live_requested:
            rows = [r for r in rows if str(r.get("mode") or "") == "live"]
    else:
        start = _parse_day(from_day, date(2021, 7, 1))
        end = _parse_day(to_day, date(2026, 6, 30))
        if end < start:
            start, end = end, start
        rows = _filter_days(_locked_rows(pack), start, end)
        src = "locked"
    return {
        "pack_id": pack.pack_id,
        "label": variant_label(pack),
        "underlying": pack.underlying,
        "variant": pack.selection,
        "source": "live" if live_requested else src,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "span": SPAN if src == "locked" else None,
        "trades": rows,
        "trade_count": len(rows),
        "total_net_pnl": round(sum(n for n in (_closed_net(r) for r in rows) if n is not None), 2),
    }


def _month_end_dd(
    months: List[Dict[str, Any]],
    capital: float,
    start: date,
    end: date,
) -> Tuple[float, float]:
    """Peak DD on month-end equity, % of start capital. Matches locked research, not daily trade path."""
    equity = capital
    peak = capital
    max_dd = 0.0
    start_ym = start.isoformat()[:7]
    end_ym = end.isoformat()[:7]
    for month in months:
        ym = str(month.get("ym") or "")[:7]
        if not ym or ym > end_ym:
            continue
        try:
            equity += float(month.get("net_pnl") or 0)
        except (TypeError, ValueError):
            continue
        if equity > peak:
            peak = equity
        if ym >= start_ym:
            max_dd = max(max_dd, peak - equity)
    pct = round((max_dd / capital) * 100.0, 2) if capital else 0.0
    return round(max_dd, 2), pct


def _covers_all_months(months: List[Dict[str, Any]], start: date, end: date) -> bool:
    yms = [str(m.get("ym") or "")[:7] for m in months if m.get("ym")]
    if not yms:
        return False
    return start.isoformat()[:7] <= yms[0] and end.isoformat()[:7] >= yms[-1]


def _locked_peak_dd(
    metrics: Dict[str, Any],
    months: List[Dict[str, Any]],
    capital: float,
    start: date,
    end: date,
) -> Tuple[float, float]:
    pct = float(metrics.get("peak_dd_pct") or 0.0)
    if months and _covers_all_months(months, start, end) and pct:
        return round(capital * pct / 100.0, 2) if capital else 0.0, pct
    if months:
        return _month_end_dd(months, capital, start, end)
    return round(capital * pct / 100.0, 2) if capital and pct else 0.0, pct


def variant_summary(
    *,
    pack_id: str,
    source: str = "locked",
    from_day: Optional[str] = None,
    to_day: Optional[str] = None,
) -> Dict[str, Any]:
    pack = paper_pack(pack_id)
    if pack is None:
        return {"error": "unknown_pack", "pack_id": pack_id}
    nifty_root, bn_root = _roots()
    root = nifty_root if pack.underlying == "NIFTY" else bn_root
    loaded = load_paper_variant(root, pack)
    alloc = loaded.get("allocation") or {}
    metrics = loaded.get("metrics") or {}
    capital = float(alloc.get("capital") or metrics.get("start_equity") or INITIAL_CAPITAL)
    ledger = variant_trades(pack_id=pack_id, source=source, from_day=from_day, to_day=to_day)
    src = str(ledger.get("source") or source)
    stats = _stats(list(ledger.get("trades") or []), capital)
    from app.research.tape_sync import sync_window

    gap = sync_window(pack)
    start = _parse_day(str(ledger.get("from") or ""), date(2021, 7, 1))
    end = _parse_day(str(ledger.get("to") or ""), date(2026, 6, 30))
    months = list(loaded.get("months") or [])
    snap = yaml_allocation(root / pack.config_rel).get("backtest_snapshot") or {}
    snap_dd = float(snap.get("peak_dd_pct") or 0)
    if src == "locked":
        if snap_dd:
            dd_pct = snap_dd
            dd_inr = round(capital * snap_dd / 100.0, 2) if capital else 0.0
        else:
            dd_inr, dd_pct = _locked_peak_dd(metrics, months, capital, start, end)
        if stats["n_trades"] > 0:
            net = stats["net_pnl"]
            ret = stats["return_pct"]
            n_trades = stats["n_trades"]
            win_rate = stats["win_rate"]
        else:
            net = float(metrics.get("net_pnl") or snap.get("net_pnl_inr") or 0.0)
            ret = float(metrics.get("return_pct") or snap.get("return_pct") or 0.0)
            n_trades = int(metrics.get("n_trades") or snap.get("n_trades") or 0)
            win_rate = stats["win_rate"]
    else:
        dd_pct = stats["dd_pct"]
        dd_inr = stats["dd_inr"]
        net = stats["net_pnl"]
        ret = stats["return_pct"]
        n_trades = stats["n_trades"]
        win_rate = stats["win_rate"]
    return {
        "pack_id": pack.pack_id,
        "label": variant_label(pack),
        "underlying": pack.underlying,
        "variant": pack.selection,
        "source": src,
        "from": ledger.get("from"),
        "to": ledger.get("to"),
        "span": SPAN,
        "capital": capital,
        "max_lots": alloc.get("max_lots"),
        "premium_inr": alloc.get("premium_inr"),
        "premium_frac": alloc.get("premium_frac"),
        "fade_lots": alloc.get("fade_lots"),
        "orb_lots": alloc.get("orb_lots"),
        "net_pnl": net,
        "return_pct": ret,
        "dd_inr": dd_inr,
        "dd_pct": dd_pct,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "locked_net_pnl": metrics.get("net_pnl"),
        "locked_return_pct": metrics.get("return_pct"),
        "locked_peak_dd_pct": metrics.get("peak_dd_pct"),
        "locked_n_trades": metrics.get("n_trades"),
        "empty": stats["n_trades"] == 0,
        "tape_exists": gap["tape_exists"],
        "tape_last_day": gap["tape_last_day"],
        "tape_net_pnl": gap.get("tape_net_pnl"),
        "paper_start": gap["paper_start"],
        "sync_from": gap["sync_from"],
        "sync_to": gap["sync_to"],
        "can_sync": gap["can_sync"],
        "today_open": gap.get("today_open"),
        "sync_status": gap["sync_status"],
        "sync_detail": gap["sync_detail"],
    }


def to_csv(trades: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_FIELDS), extrasaction="ignore")
    writer.writeheader()
    for row in trades:
        writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
    return buf.getvalue()
