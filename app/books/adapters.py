"""Per-underlying Edge Lab book adapters (shadow journal + execution state)."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.session import session_day as _session_day, to_utc_z


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
            rejected.append(
                {
                    "trace_id": trace,
                    "symbol": sym,
                    "stage": "gate" if status == "ok" and not tradeable else "signal",
                    "reason": (r.get("execution") or {}).get("reason") or status or "skip",
                    "underlying": underlying,
                }
            )
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


def sleeve_gates(book: BookPaths, day: Optional[date] = None) -> List[Dict[str, Any]]:
    day = day or _session_day()
    out: List[Dict[str, Any]] = []
    for sleeve in ("fade", "orb"):
        g = check_book_gate(book, sleeve=sleeve, day=day)
        reason = g.get("reason")
        if reason in ("", "ok", "OK"):
            reason = None
        out.append(
            {
                "sleeve": sleeve,
                "allow": bool(g.get("allow")),
                "lots": int(g.get("lots") or 0),
                "reason": None if g.get("allow") else reason,
            }
        )
    return out


def books_snapshot(
    books: List[BookPaths],
    *,
    position_rows: Optional[List[dict]] = None,
) -> List[Dict[str, Any]]:
    by_und: Dict[str, List[dict]] = {"NIFTY": [], "BANKNIFTY": []}
    for row in position_rows or []:
        u = str(row.get("underlying") or "")
        if u in by_und:
            by_und[u].append(row)
    out: List[Dict[str, Any]] = []
    for b in books:
        st = load_execution_state(b)
        default_cap = 100_000.0 if b.name == "NIFTY" else 200_000.0
        capital = float(st.get("capital") or st.get("starting_capital") or default_cap)
        equity = float(st.get("equity") or capital)
        rows = by_und.get(b.name) or []
        open_mtm = round(sum(float(r.get("unrealized_pnl") or 0) for r in rows), 2)
        open_lots = int(sum(int(r.get("lots") or 0) for r in rows))
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
            }
        )
    return out


def circuit_from_books(books: List[BookPaths]) -> Dict[str, Any]:
    tripped = False
    soft = False
    reason = ""
    max_dd = 0.0
    for b in books:
        st = load_execution_state(b)
        eq = float(st.get("equity") or 0)
        peak = float(st.get("peak_equity") or eq or 1)
        dd = max(0.0, (peak - eq) / peak) if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        if str(st.get("dd_mode") or "") == "halted":
            tripped = True
            reason = f"{b.name} peak-DD halt"
        if st.get("month_halted") or st.get("month_ce_halt"):
            soft = True
            if not reason:
                reason = f"{b.name} month halt"
    return {
        "tripped": tripped,
        "soft_halt": soft,
        "trip_reason": reason,
        "limits": {
            "daily_loss_limit_inr": 0,
            "max_drawdown_from_peak_pct": 0.20,
        },
        "portfolio_unrealized_pnl": None,
        "mtm_stale": None,
        "peak_dd_pct": round(100.0 * max_dd, 2),
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


def trades_today(books: List[BookPaths], day: Optional[str] = None) -> Dict[str, Any]:
    """Closed (and still-open) rounds from today's shadow journals — not live positions."""
    day = day or _session_day().isoformat()
    trades: List[dict] = []
    for b in books:
        for i, r in enumerate(_read_journal(b, day, strict_day=True)):
            lab = r.get("lab") or {}
            fill = r.get("broker_fill") if isinstance(r.get("broker_fill"), dict) else {}
            bo = r.get("broker_order") if isinstance(r.get("broker_order"), dict) else {}
            entry = _num(fill.get("entry") if fill else None) or _num(lab.get("entry"))
            exit_px = _num(fill.get("exit") if fill else None) or _num(lab.get("exit"))
            pnl = _num((fill or {}).get("net_pnl"))
            if pnl is None:
                pnl = _num(lab.get("net_pnl"))
            costs = _num((fill or {}).get("costs")) or _num(lab.get("costs")) or 0.0
            net = _num((fill or {}).get("net_pnl"))
            if net is None:
                net = (round(pnl - costs, 2) if pnl is not None else None)
            exit_reason = str(lab.get("exit_reason") or (fill or {}).get("exit_reason") or "")
            has_order = bool(bo) or bool(fill) or entry is not None
            if not has_order and not exit_reason:
                continue
            if not exit_reason:
                exit_reason = "take_profit" if (fill or {}).get("notes") else ("open" if exit_px is None else "exit")
            if exit_px is None and exit_reason in ("", "open"):
                exit_reason = "open"
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
                pnl = None
                net = None
            lab_entry = _num(lab.get("entry"))
            lab_exit = _num(lab.get("exit"))
            broker_entry = _num((fill or {}).get("entry")) or entry
            broker_exit = _num((fill or {}).get("exit")) or exit_px
            slip_entry = None
            slip_exit = None
            if lab_entry is not None and broker_entry is not None:
                slip_entry = round(broker_entry - lab_entry, 4)
            if lab_exit is not None and broker_exit is not None:
                slip_exit = round(broker_exit - lab_exit, 4)
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
                    "lab_entry": lab_entry,
                    "broker_entry": broker_entry,
                    "lab_exit": lab_exit,
                    "broker_exit": broker_exit,
                    "slip_entry": slip_entry,
                    "slip_exit": slip_exit,
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
            if bo or fill:
                status = "EXECUTED"
            elif not tradeable or (status_lab and status_lab != "ok"):
                status = "SKIPPED" if "skip" in str(exe.get("reason") or status_lab).lower() else "REJECTED"
            else:
                status = "PENDING"
            opt = str(lab.get("side") or "").upper()
            notes = str(exe.get("reason") or lab.get("notes") or status_lab or "")
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
