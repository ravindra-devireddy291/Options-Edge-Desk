"""Per-underlying Edge Lab book adapters (shadow journal + execution state)."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.session import market_session, session_day as _session_day, to_utc_z


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class BookPaths:
    name: str  # NIFTY | BANKNIFTY
    lab_root: Path
    config_rel: str
    shadow_dir: Path

    @property
    def config_path(self) -> Path:
        return self.lab_root / self.config_rel

    @property
    def state_path(self) -> Path:
        return self.shadow_dir / "execution_state.json"


def nifty_book(lab_root: Path, config_rel: str) -> BookPaths:
    return BookPaths(
        name="NIFTY",
        lab_root=lab_root,
        config_rel=config_rel,
        shadow_dir=lab_root / "reports" / "shadow",
    )


def bn_book(lab_root: Path, config_rel: str) -> BookPaths:
    return BookPaths(
        name="BANKNIFTY",
        lab_root=lab_root,
        config_rel=config_rel,
        shadow_dir=lab_root / "reports" / "shadow",
    )


def load_execution_state(book: BookPaths) -> Dict[str, Any]:
    p = book.state_path
    if not p.exists():
        return {
            "equity": 200_000.0,
            "peak_equity": 200_000.0,
            "dd_mode": "live",
            "month_halted": False,
            "month_ce_halt": False,
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def paper_book_start() -> date:
    """IST day paper month begins — Home equity ignores older lab shadow P&L."""
    import os

    raw = (os.environ.get("DESK_PAPER_BOOK_START") or "2026-08-17").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return date(2026, 8, 17)


def paper_period_realized(book: BookPaths, *, start: Optional[date] = None) -> Dict[str, Any]:
    """Sum closed journal PnL from paper start → today (not full lab lifetime equity)."""
    start = start or paper_book_start()
    end = _session_day()
    realized = 0.0
    trade_count = 0
    for path in sorted(book.shadow_dir.glob("shadow_*.jsonl")):
        day_s = path.name.replace("shadow_", "").replace(".jsonl", "")
        try:
            day = date.fromisoformat(day_s)
        except ValueError:
            continue
        if day < start or day > end:
            continue
        for r in _read_journal(book, day_s, strict_day=True):
            if not _journal_row_is_trade(r):
                continue
            lab = r.get("lab") or {}
            status = str(lab.get("status") or "")
            if status.startswith("skip"):
                continue
            fill = r.get("broker_fill") if isinstance(r.get("broker_fill"), dict) else {}
            bo = r.get("broker_order") if isinstance(r.get("broker_order"), dict) else {}
            round_ = _round_from_journal(lab, fill, bo, day=day_s)
            if round_["exit_reason"] == "open" or round_["pnl"] is None:
                continue
            realized += float(round_["pnl"])
            trade_count += 1
    return {
        "paper_start": start.isoformat(),
        "realized_pnl": round(realized, 2),
        "trade_count": trade_count,
    }


def book_capital(book: BookPaths) -> float:
    st = load_execution_state(book)
    default_cap = 100_000.0 if book.name == "NIFTY" else 200_000.0
    return float(st.get("capital") or st.get("starting_capital") or default_cap)


def _read_journal(book: BookPaths, day: Optional[str] = None, *, strict_day: bool = False) -> List[Dict[str, Any]]:
    day = day or _session_day().isoformat()
    path = book.shadow_dir / f"shadow_{day}.jsonl"
    if not path.exists():
        if strict_day:
            return []
        # fall back to latest journal file
        files = sorted(book.shadow_dir.glob("shadow_*.jsonl"))
        if not files:
            return []
        path = files[-1]
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _as_utc_z(ts: Any, *, day: Optional[str] = None) -> str:
    """Best-effort ISO-Z timestamp for decision-log rows (no secrets)."""
    if isinstance(ts, str) and ts.strip():
        s = ts.strip().replace(" ", "T")
        if s.endswith("Z") or "+" in s[10:] or s.endswith("+00:00"):
            return s.replace("+00:00", "Z") if s.endswith("+00:00") else s
        if len(s) >= 19:
            return s[:19] + "Z"
        if len(s) == 10:
            return s + "T00:00:00Z"
    if day and len(str(day)) >= 10:
        return str(day)[:10] + "T00:00:00Z"
    return _now()


def _reject_stage(status: str, tradeable: bool, execution: dict) -> str:
    """gate | signal | oms — stable strings for UI decision log."""
    if status == "ok" and not tradeable:
        return "gate"
    reason = str((execution or {}).get("reason") or "").lower()
    if any(k in reason for k in ("oms", "broker", "order", "place", "reject")):
        return "oms"
    if (execution or {}).get("allow") is False and status == "ok":
        return "gate"
    return "signal"


def _reject_reason(status: str, execution: dict) -> str:
    """Prefer lab snake_case status codes; UI humanizes."""
    st = (status or "").strip()
    if st and st.lower() not in ("ok", "ok_trade", ""):
        return st
    ex = str((execution or {}).get("reason") or "").strip()
    if ex and ex.lower() not in ("ok", ""):
        return ex
    return "skip"


def normalize_rejected_row(
    book: BookPaths,
    r: Dict[str, Any],
    *,
    day: Optional[str] = None,
    index: int = 0,
) -> Dict[str, Any]:
    """UI-safe rejected / skip row — no tokens, PIN, or broker secrets."""
    lab = r.get("lab") if isinstance(r.get("lab"), dict) else {}
    execution = r.get("execution") if isinstance(r.get("execution"), dict) else {}
    sleeve = str(r.get("sleeve") or lab.get("sleeve") or "fade").lower()
    if sleeve not in ("fade", "orb"):
        sleeve = "fade"
    underlying = book.name
    status = str(lab.get("status") or "")
    tradeable = bool(r.get("tradeable")) if "tradeable" in r else status == "ok"
    day_s = str(lab.get("day") or day or "")
    sym_raw = lab.get("symbol")
    symbol = str(sym_raw).strip() if sym_raw not in (None, "") else None
    notes = execution.get("notes") or lab.get("notes") or r.get("notes")
    if notes is not None:
        notes = str(notes).strip() or None
    return {
        "trace_id": f"{underlying}:{sleeve}:{day_s or index}",
        "underlying": underlying,
        "sleeve": sleeve,
        "stage": _reject_stage(status, tradeable, execution),
        "reason": _reject_reason(status, execution),
        "symbol": symbol,
        "at": _as_utc_z(r.get("ts") or lab.get("ts"), day=day_s or None),
        "notes": notes,
    }


def signals_from_book(book: BookPaths, day: Optional[str] = None) -> Tuple[List[dict], List[dict], Dict[str, int]]:
    rows = _read_journal(book, day)
    approved: List[dict] = []
    rejected: List[dict] = []
    for i, r in enumerate(rows):
        lab = r.get("lab") or {}
        sleeve = str(r.get("sleeve") or "fade")
        underlying = book.name
        status = str(lab.get("status") or "")
        tradeable = bool(r.get("tradeable")) if "tradeable" in r else status == "ok"
        sym = str(lab.get("symbol") or f"{underlying}-{sleeve}")
        trace = f"{underlying}:{sleeve}:{lab.get('day') or day or i}"
        if status == "ok" and tradeable:
            sec = (
                lab.get("security_id")
                or lab.get("securityId")
                or (r.get("broker") or {}).get("security_id")
                or (r.get("broker_order") or {}).get("security_id")
                or ""
            )
            strike = lab.get("strike")
            side_opt = str(lab.get("side") or "").upper()  # CE/PE
            lots = int((r.get("execution") or {}).get("lots") or lab.get("lots") or 0) or None
            qty = int(lab.get("qty") or 0) or None
            lot_size = int(lab.get("lot_size") or 0) or None
            # resolve missing security_id from scrip master when possible
            if (not sec or str(sec) == "0") and (sym or (strike and side_opt in ("CE", "PE"))):
                try:
                    from app.brokers.dhan.contracts import resolve_contract

                    day_s = str(lab.get("day") or day or date.today().isoformat())
                    c = resolve_contract(
                        underlying=underlying,
                        strike=float(strike) if strike not in (None, "", 0, 0.0) else None,
                        option_type=side_opt if side_opt in ("CE", "PE") else None,
                        symbol=sym if sym and "NIFTY" in sym.upper() else None,
                        session_day=date.fromisoformat(day_s) if len(day_s) >= 10 else date.today(),
                    )
                    sec = c.security_id
                    lot_size = c.lot_size
                    if not sym or sym.endswith(("-fade", "-orb", "-FADE", "-ORB")):
                        sym = c.tradingsymbol
                except Exception:
                    pass
            if lots and lot_size and not qty:
                qty = int(lots) * int(lot_size)
            elif qty and lot_size and not lots:
                lots = max(1, int(qty) // int(lot_size))
            approved.append(
                {
                    "trace_id": trace,
                    "symbol": sym,
                    "signal_type": sleeve,
                    "quantity": qty,
                    "lots": lots,
                    "lot_size": lot_size,
                    "confidence": 1.0,
                    "executed": bool(r.get("broker_fill")),
                    "underlying": underlying,
                    "side": "BUY",  # fade/orb entries are long options in this book
                    "option_type": side_opt if side_opt in ("CE", "PE") else None,
                    "strike": strike,
                    "security_id": str(sec) if sec else "",
                    "day": lab.get("day"),
                    "tradeable": True,
                    "net_pnl": lab.get("net_pnl"),
                    "exit_reason": lab.get("exit_reason"),
                    "broker_order": r.get("broker_order"),
                }
            )
        else:
            rejected.append(normalize_rejected_row(book, r, day=day, index=i))
    funnel = {
        "collected": len(rows),
        "after_gates": len(approved) + sum(1 for x in rejected if x["stage"] == "gate"),
        "after_enrich": len(approved),
        "after_combined": len(approved),
        "after_exposure": len(approved),
        "approved": len(approved),
        "executed": sum(1 for a in approved if a.get("executed")),
        "exits_executed": sum(1 for a in approved if a.get("executed")),
    }
    return approved, rejected, funnel


def last_cycle_signals(books: List[BookPaths]) -> Dict[str, Any]:
    approved: List[dict] = []
    rejected: List[dict] = []
    funnel = {
        "collected": 0,
        "after_gates": 0,
        "after_enrich": 0,
        "after_combined": 0,
        "after_exposure": 0,
        "approved": 0,
        "executed": 0,
        "exits_executed": 0,
    }
    for b in books:
        a, r, f = signals_from_book(b)
        approved.extend(a)
        rejected.extend(r)
        for k in funnel:
            funnel[k] += int(f.get(k) or 0)
    return {
        "cycle_number": 1,
        "success": True,
        "reason": None,
        "funnel": funnel,
        "approved": approved,
        "rejected": rejected,
        "snapshot_at": _now(),
    }


def rejected_only(books: List[BookPaths]) -> Dict[str, Any]:
    rows: List[dict] = []
    for b in books:
        _, r, _ = signals_from_book(b)
        rows.extend(r)
    return {"count": len(rows), "rows": rows, "snapshot_at": _now()}


def shadow_book_status(books: List[BookPaths]) -> Dict[str, Any]:
    halted = False
    halted_underlyings: List[str] = []
    positions: List[dict] = []
    disc: List[str] = []
    for b in books:
        st = load_execution_state(b)
        if str(st.get("dd_mode") or "") == "halted" or st.get("month_halted"):
            halted = True
            halted_underlyings.append(b.name)
            disc.append(f"{b.name}:halted")
    return {
        "halted": halted,
        "halted_underlyings": halted_underlyings,
        "enabled": True,
        "positions": positions,
        "last_reconcile": {"ok": len(disc) == 0, "discrepancies": disc},
    }


def book_is_halted(book: BookPaths) -> bool:
    st = load_execution_state(book)
    return str(st.get("dd_mode") or "") == "halted" or bool(st.get("month_halted"))


def _book_label(capital: float) -> str:
    lakhs = capital / 100_000.0
    if abs(lakhs - round(lakhs)) < 0.051:
        n = int(round(lakhs))
        return f"Rs {n}L book"
    return f"Rs {int(capital)} book"


def _round_money(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _round_frac(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _public_gate_row(sleeve: str, g: Dict[str, Any]) -> Dict[str, Any]:
    """UI-facing sleeve gate: allow/lots/reason + GateDecision headroom fields."""
    reason = g.get("reason")
    if reason in ("", "ok", "OK"):
        reason = None
    allow = bool(g.get("allow"))
    return {
        "sleeve": sleeve,
        "allow": allow,
        "lots": int(g.get("lots") or 0),
        "reason": None if allow else reason,
        "dd_mode": g.get("dd_mode"),
        "dd_pct": _round_frac(g.get("dd_pct")),
        "day_pnl": _round_money(g.get("day_pnl")),
        "month_pnl": _round_money(g.get("month_pnl")),
        "daily_cap": _round_money(g.get("daily_cap")),
        "monthly_cap": _round_money(g.get("monthly_cap")),
        "premium_budget": _round_money(g.get("premium_budget")),
        "deploy_frac": _round_frac(g.get("deploy_frac")),
    }


def sleeve_gates(book: BookPaths, day: Optional[date] = None) -> List[Dict[str, Any]]:
    day = day or _session_day()
    out: List[Dict[str, Any]] = []
    for sleeve in ("fade", "orb"):
        g = check_book_gate(book, sleeve=sleeve, day=day)
        out.append(_public_gate_row(sleeve, g))
    return out


def books_snapshot(
    books: List[BookPaths],
    *,
    position_rows: Optional[List[dict]] = None,
) -> List[Dict[str, Any]]:
    """Home book cards: capital + paper-period realized + open MTM (not lifetime lab equity)."""
    by_und: Dict[str, List[dict]] = {"NIFTY": [], "BANKNIFTY": []}
    for row in position_rows or []:
        u = str(row.get("underlying") or "")
        if u in by_und:
            by_und[u].append(row)
    out: List[Dict[str, Any]] = []
    for b in books:
        capital = book_capital(b)
        period = paper_period_realized(b)
        rows = by_und.get(b.name) or []
        open_mtm = round(sum(float(r.get("unrealized_pnl") or 0) for r in rows), 2)
        open_lots = int(sum(int(r.get("lots") or 0) for r in rows))
        equity = round(capital + float(period["realized_pnl"]) + open_mtm, 2)
        out.append(
            {
                "underlying": b.name,
                "label": _book_label(capital),
                "capital": capital,
                "equity": equity,
                "open_mtm": open_mtm,
                "open_lots": open_lots,
                "halted": book_is_halted(b),
                "gates": sleeve_gates(b),
                "paper_start": period["paper_start"],
                "paper_realized": period["realized_pnl"],
                "paper_trade_count": period["trade_count"],
            }
        )
    return out


def _circuit_limits(book: BookPaths) -> Dict[str, Any]:
    """Daily loss / max DD limits from lab book config (same brakes as gates)."""
    daily: Optional[float] = None
    max_dd = 0.20
    try:
        ensure_lab_on_path(book.lab_root)
        from edge_lab.risk.execution_brakes import load_book_config  # type: ignore

        cfg = load_book_config(book.config_path)
        max_dd = float(getattr(cfg, "max_dd_pct", None) or 0.20)
        st = load_execution_state(book)
        eq = float(st.get("equity") or 0) or None
        if hasattr(cfg, "daily_cap_for"):
            daily = cfg.daily_cap_for(eq)
        elif hasattr(cfg, "daily_cap"):
            daily = cfg.daily_cap
    except Exception:
        pass
    return {
        "daily_loss_limit_inr": _round_money(daily),
        "max_drawdown_from_peak_pct": _round_frac(max_dd) if max_dd is not None else 0.20,
    }


def _book_dd_pct(st: Dict[str, Any]) -> float:
    eq = float(st.get("equity") or 0)
    peak = float(st.get("peak_equity") or eq or 1)
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - eq) / peak)


def circuit_from_books(books: List[BookPaths]) -> Dict[str, Any]:
    """Home Risk circuit read model — GET only; reuses execution_state / lab brakes."""
    tripped = False
    soft = False
    reason: Optional[str] = None
    max_dd = 0.0
    book_rows: List[Dict[str, Any]] = []
    for b in books:
        st = load_execution_state(b)
        dd = _book_dd_pct(st)
        max_dd = max(max_dd, dd)
        dd_mode = str(st.get("dd_mode") or "live")
        month_soft = bool(st.get("month_halted") or st.get("month_ce_halt"))
        day_soft = bool(st.get("day_daily_halt"))
        if dd_mode == "halted":
            tripped = True
            reason = f"{b.name} peak-DD halt"
        if month_soft or day_soft:
            soft = True
            if not reason:
                reason = f"{b.name} month halt" if month_soft else f"{b.name} daily halt"
        book_rows.append(
            {
                "underlying": b.name,
                "dd_pct": _round_frac(dd),
                "dd_mode": dd_mode,
                "day_pnl": _round_money(st.get("day_pnl")),
                "month_pnl": _round_money(st.get("month_pnl")),
            }
        )
    limits = (
        _circuit_limits(books[0])
        if books
        else {"daily_loss_limit_inr": None, "max_drawdown_from_peak_pct": 0.20}
    )
    return {
        "tripped": tripped,
        "soft_halt": soft,
        "trip_reason": reason,
        "peak_dd_pct": _round_frac(max_dd),
        "limits": limits,
        "books": book_rows,
        "portfolio_unrealized_pnl": None,
        "mtm_stale": None,
    }


def ensure_lab_on_path(lab_root: Path) -> None:
    s = str(lab_root)
    if s not in sys.path:
        sys.path.insert(0, s)


def book_by_underlying(books: List[BookPaths], underlying: str) -> Optional[BookPaths]:
    u = (underlying or "").upper()
    for b in books:
        if b.name == u:
            return b
    return None


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _time_ist(row: Dict[str, Any]) -> str:
    ts = str(row.get("ts") or "")
    # "2026-08-14T09:30:00" or with timezone
    if "T" in ts and len(ts) >= 19:
        return ts[11:19]
    return ts or ""


def _journal_row_is_trade(r: Dict[str, Any]) -> bool:
    """True only for desk/broker rounds — not lab-only shadow cards (those stay on compass)."""
    fill = r.get("broker_fill") if isinstance(r.get("broker_fill"), dict) else {}
    bo = r.get("broker_order") if isinstance(r.get("broker_order"), dict) else {}
    return bool(bo or fill)


def _lab_eod_still_provisional(exit_reason: str, day: Optional[str]) -> bool:
    """
    Intraday shadow re-runs write exit_reason=eod + last-bar mark before the
    session is actually flat. Treat that as open until NSE close on that day.
    """
    reason = str(exit_reason or "").strip().lower().replace("-", "_").replace(" ", "_")
    if reason not in ("eod", "eod_flatten"):
        return False
    today = _session_day()
    try:
        d = date.fromisoformat(day) if day else today
    except ValueError:
        d = today
    if d != today:
        return False
    return market_session() != "closed"


def _open_round(
    *,
    entry: Optional[float],
    lab_entry: Optional[float],
    lab_exit: Optional[float],
    broker_entry: Optional[float],
    costs: float,
) -> Dict[str, Any]:
    return {
        "entry": entry,
        "exit_px": None,
        "exit_reason": "open",
        "pnl": None,
        "net": None,
        "costs": costs,
        "lab_entry": lab_entry,
        "lab_exit": lab_exit,
        "broker_entry": broker_entry if broker_entry is not None else entry,
        "broker_exit": None,
        "slip_entry": None,
        "slip_exit": None,
    }


def _round_from_journal(
    lab: Dict[str, Any],
    fill: Dict[str, Any],
    bo: Dict[str, Any],
    *,
    day: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve entry/exit/PnL for blotter.

    Lab cards carry a *planned* exit (often eod) before the broker closes.
    Once a desk order/fill exists, stay OPEN until broker_fill.exit is set —
    otherwise open paper looks closed and lab MTM keeps rewriting the row.
    Lab-only eod on the live session day stays OPEN until market close.
    """
    broker_entry = _num(fill.get("entry"))
    broker_exit = _num(fill.get("exit"))
    lab_entry = _num(lab.get("entry"))
    lab_exit = _num(lab.get("exit"))
    entry = broker_entry if broker_entry is not None else lab_entry
    has_broker = bool(bo) or bool(fill)
    costs_open = _num(fill.get("costs")) or _num(lab.get("costs")) or 0.0

    if has_broker and broker_exit is None:
        return _open_round(
            entry=entry,
            lab_entry=lab_entry,
            lab_exit=lab_exit,
            broker_entry=broker_entry,
            costs=costs_open,
        )

    if has_broker:
        exit_px = broker_exit
        exit_reason = str(fill.get("exit_reason") or lab.get("exit_reason") or "exit")
        pnl = _num(fill.get("net_pnl"))
        costs = costs_open
        net = pnl if pnl is not None else None
    else:
        exit_px = lab_exit
        exit_reason = str(lab.get("exit_reason") or "")
        pnl = _num(lab.get("net_pnl"))
        costs = _num(lab.get("costs")) or 0.0
        if not exit_reason:
            exit_reason = "open" if exit_px is None else "exit"
        if exit_px is None and exit_reason in ("", "open"):
            exit_reason = "open"
        if _lab_eod_still_provisional(exit_reason, day):
            return _open_round(
                entry=entry,
                lab_entry=lab_entry,
                lab_exit=lab_exit,
                broker_entry=broker_entry,
                costs=costs,
            )
        net = round(pnl - costs, 2) if pnl is not None else None

    if exit_reason == "open":
        exit_px = None
        pnl = None
        net = None

    slip_entry = None
    slip_exit = None
    broker_entry_disp = broker_entry if broker_entry is not None else entry
    broker_exit_disp = broker_exit if broker_exit is not None else (None if has_broker else exit_px)
    if lab_entry is not None and broker_entry_disp is not None:
        slip_entry = round(float(broker_entry_disp) - float(lab_entry), 4)
    if lab_exit is not None and broker_exit_disp is not None:
        slip_exit = round(float(broker_exit_disp) - float(lab_exit), 4)

    return {
        "entry": entry,
        "exit_px": exit_px,
        "exit_reason": exit_reason,
        "pnl": pnl,
        "net": net,
        "costs": costs,
        "lab_entry": lab_entry,
        "lab_exit": lab_exit,
        "broker_entry": broker_entry_disp,
        "broker_exit": broker_exit_disp,
        "slip_entry": slip_entry,
        "slip_exit": slip_exit,
    }


def trades_today(books: List[BookPaths], day: Optional[str] = None) -> Dict[str, Any]:
    """Closed (and still-open) rounds from today's shadow journals — not live positions."""
    day = day or _session_day().isoformat()
    trades: List[dict] = []
    for b in books:
        for i, r in enumerate(_read_journal(b, day, strict_day=True)):
            if not _journal_row_is_trade(r):
                continue
            lab = r.get("lab") or {}
            fill = r.get("broker_fill") if isinstance(r.get("broker_fill"), dict) else {}
            bo = r.get("broker_order") if isinstance(r.get("broker_order"), dict) else {}
            round_ = _round_from_journal(lab, fill, bo, day=day)
            entry = round_["entry"]
            exit_px = round_["exit_px"]
            exit_reason = round_["exit_reason"]
            pnl = round_["pnl"]
            net = round_["net"]
            costs = round_["costs"]
            has_order = bool(bo) or bool(fill) or entry is not None
            if not has_order and not exit_reason:
                continue
            qty = int((fill or {}).get("qty") or lab.get("qty") or bo.get("quantity") or 0)
            lots = int(bo.get("lots") or (r.get("execution") or {}).get("lots") or lab.get("lots") or 0)
            lot_size = int(lab.get("lot_size") or bo.get("lot_size") or 0) or 0
            if lots and lot_size and not qty:
                qty = lots * lot_size
            if qty and lot_size and not lots:
                lots = max(1, qty // lot_size)
            trade_id = str(
                bo.get("client_order_id")
                or bo.get("broker_order_id")
                or f"{b.name}:{r.get('sleeve') or 'fade'}:{day}:{i}"
            )
            closed_at = (fill or {}).get("recorded_at") or r.get("ts") or None
            if exit_reason == "open":
                closed_at = None
            closed_iso = closed_at
            if closed_at and "Z" not in str(closed_at) and "T" in str(closed_at):
                try:
                    from datetime import datetime as _dt

                    dt = _dt.fromisoformat(str(closed_at).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        from app.session import IST

                        dt = dt.replace(tzinfo=IST)
                    closed_iso = to_utc_z(dt)
                except Exception:
                    closed_iso = closed_at
            trades.append(
                {
                    "trade_id": trade_id,
                    "underlying": b.name,
                    "sleeve": str(r.get("sleeve") or "fade").lower(),
                    "symbol": str(lab.get("symbol") or bo.get("symbol") or ""),
                    "side": str(bo.get("side") or "BUY"),
                    "qty": qty,
                    "lots": lots,
                    "lot_size": lot_size,
                    "entry_price": entry,
                    "exit_price": exit_px,
                    "exit_reason": exit_reason,
                    "realized_pnl": pnl,
                    "costs": costs,
                    "net_pnl": net,
                    "lab_entry": round_["lab_entry"],
                    "broker_entry": round_["broker_entry"],
                    "lab_exit": round_["lab_exit"],
                    "broker_exit": round_["broker_exit"],
                    "slip_entry": round_.get("slip_entry"),
                    "slip_exit": round_.get("slip_exit"),
                    "closed_at": closed_iso,
                }
            )
    realized = [t for t in trades if t.get("exit_reason") not in ("open", "") and t.get("realized_pnl") is not None]
    total = round(sum(float(t["realized_pnl"]) for t in realized), 2)
    total_costs = round(sum(float(t.get("costs") or 0) for t in trades), 2)
    total_net = round(sum(float(t["net_pnl"]) for t in realized if t.get("net_pnl") is not None), 2)
    lots_traded = int(sum(int(t.get("lots") or 0) for t in trades))
    return {
        "day": day,
        "trades": trades,
        "total_realized_pnl": total,
        "total_costs": total_costs,
        "total_net_pnl": total_net,
        "trade_count": len(trades),
        "closed_count": len(realized),
        "lots_traded": lots_traded,
    }


def signals_today(books: List[BookPaths], day: Optional[str] = None) -> Dict[str, Any]:
    """Today's engine Trade Cards (compass) vs fills — Gate 5 shadow."""
    day = day or _session_day().isoformat()
    signals: List[dict] = []
    for b in books:
        idx = 0
        for r in _read_journal(b, day, strict_day=True):
            lab = r.get("lab") or {}
            exe = r.get("execution") if isinstance(r.get("execution"), dict) else {}
            fill = r.get("broker_fill") if isinstance(r.get("broker_fill"), dict) else {}
            bo = r.get("broker_order") if isinstance(r.get("broker_order"), dict) else {}
            status_lab = str(lab.get("status") or "")
            tradeable = bool(r.get("tradeable")) if "tradeable" in r else status_lab == "ok"
            skip_blob = f"{status_lab} {exe.get('reason') or ''} {lab.get('notes') or ''}".lower()
            if bo or fill:
                status = "EXECUTED"
            elif not tradeable or (status_lab and status_lab != "ok"):
                status = "SKIPPED" if "skip" in skip_blob else "REJECTED"
            else:
                status = "PENDING"
            opt = str(lab.get("side") or "").upper()
            notes = status_lab if status_lab and status_lab not in ("ok", "OK") else str(exe.get("reason") or lab.get("notes") or status_lab or "")
            idx += 1
            sleeve = str(r.get("sleeve") or "fade").lower()
            created = r.get("ts")
            created_iso = None
            if created:
                try:
                    from datetime import datetime as _dt
                    from app.session import IST

                    dt = _dt.fromisoformat(str(created).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=IST)
                    created_iso = to_utc_z(dt)
                except Exception:
                    created_iso = str(created)
            signals.append(
                {
                    "signal_id": f"{b.name.lower()}-{sleeve}-{day}-{idx}",
                    "day": day,
                    "time": _time_ist(r),
                    "underlying": b.name,
                    "sleeve": sleeve,
                    "action": str(lab.get("action") or bo.get("side") or "BUY").upper()
                    if str(lab.get("action") or "").upper() in ("BUY", "SELL")
                    else "BUY",
                    "option_type": opt if opt in ("CE", "PE") else None,
                    "target_strike": _num(lab.get("strike")),
                    "target_lots": int(exe.get("lots") or lab.get("lots") or bo.get("lots") or 0) or None,
                    "gap_pts": _num(lab.get("gap_pts")),
                    "status": status,
                    "notes": notes,
                    "symbol": str(lab.get("symbol") or ""),
                    "expiry": lab.get("expiry"),
                    "security_id": str(lab.get("security_id") or lab.get("securityId") or ""),
                    "ltp": _num(lab.get("ltp") or lab.get("entry")),
                    "created_at": created_iso,
                }
            )
    return {"day": day, "signals": signals, "count": len(signals)}


def rebuild_books_from_shadow(books: List[BookPaths]) -> Dict[str, Any]:
    rebuilt: List[str] = []
    errors: List[str] = []
    for b in books:
        try:
            ensure_lab_on_path(b.lab_root)
            from edge_lab.risk.execution_brakes import (  # type: ignore
                load_book_config,
                rebuild_state_from_shadow,
                save_state,
            )

            cfg = load_book_config(b.config_path)
            state = rebuild_state_from_shadow(b.shadow_dir, cfg, prefer_broker=True)
            save_state(b.state_path, state)
            rebuilt.append(b.name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{b.name}:{exc}")
    return {"rebuilt": rebuilt, "errors": errors}


def check_book_gate(
    book: BookPaths,
    *,
    sleeve: str = "fade",
    day: Optional[date] = None,
) -> Dict[str, Any]:
    """Run Edge Lab execution_brakes.check_gate for one underlying."""
    ensure_lab_on_path(book.lab_root)
    try:
        from edge_lab.risk.execution_brakes import (  # type: ignore
            check_gate,
            load_book_config,
            load_state,
            rebuild_state_from_shadow,
        )
    except Exception as exc:  # noqa: BLE001
        return {"allow": False, "reason": f"brakes_import_error:{exc}", "lots": 0}

    day = day or _session_day()
    try:
        cfg = load_book_config(book.config_path)
        state_path = book.state_path
        if state_path.exists():
            state = load_state(state_path, cfg)
        else:
            state = rebuild_state_from_shadow(book.shadow_dir, cfg, prefer_broker=True)
        g = check_gate(cfg, state, day=day, sleeve=sleeve.lower())
        payload = (
            g.as_dict()
            if hasattr(g, "as_dict")
            else {
                "allow": bool(g.allow),
                "reason": str(g.reason),
                "lots": int(g.lots),
            }
        )
        reason = str(payload.get("reason") or "")
        if not payload.get("allow") and sleeve.lower() == "orb" and "fade" in reason.lower():
            payload["reason"] = "ORB is denied after a fade loss"
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"allow": False, "reason": f"gate_error:{exc}", "lots": 0}


def sleeve_risk_params(book: BookPaths, sleeve: str) -> tuple[float, float]:
    """Stop / TP fractions from lab YAML (fade or orb)."""
    ensure_lab_on_path(book.lab_root)
    try:
        from edge_lab.risk.execution_brakes import load_book_config  # type: ignore

        cfg = load_book_config(book.config_path)
        if sleeve.lower() == "orb":
            o = cfg.orb or {}
            return float(o.get("stop_pct") or 0.25), float(o.get("take_profit_pct") or 0.80)
        f = cfg.fade or {}
        return float(f.get("stop_pct") or 0.30), float(f.get("take_profit_pct") or 0.50)
    except Exception:
        return 0.30, 0.50
