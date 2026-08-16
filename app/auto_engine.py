"""Paper/live auto: dispatch PENDING compass cards to Dhan without UI approval."""
from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

from app import triggers as trigger_store
from app.books import adapters as books
from app.brokers.dhan import client as dhan
from app.oms import place_paper
from app.runners.state import RUNNER
from app.session import market_session, session_day

_STATE = Path(__file__).resolve().parents[1] / "data" / "auto_state.json"
_fired: Set[str] = set()
_eod_done_day: Optional[str] = None
_loaded_day: Optional[str] = None


def load_persisted() -> None:
    global _eod_done_day, _loaded_day
    day = session_day().isoformat()
    if _loaded_day == day:
        return
    _fired.clear()
    _eod_done_day = None
    _loaded_day = day
    if not _STATE.exists():
        return
    try:
        raw = json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return
    if str(raw.get("day") or "") != day:
        return
    _fired.update(str(x) for x in (raw.get("fired") or []))
    _eod_done_day = raw.get("eod_done_day")


def _save() -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(
        json.dumps(
            {
                "day": session_day().isoformat(),
                "fired": sorted(_fired),
                "eod_done_day": _eod_done_day,
            }
        ),
        encoding="utf-8",
    )


def reset() -> None:
    _fired.clear()
    _save()


def _books() -> List:
    from app.auth import get_settings

    s = get_settings()
    return [
        books.nifty_book(s.nifty_lab_root, s.nifty_config),
        books.bn_book(s.bn_lab_root, s.bn_config),
    ]


def _notice_from_place(signal: Dict[str, Any], result: Dict[str, Any]) -> None:
    order = result.get("order") or {}
    contract = result.get("contract") or {}
    side = str(order.get("side") or signal.get("action") or "BUY").upper()
    kind = "sell" if side == "SELL" else "buy"
    trigger_store.push_fill_notice(
        trigger_id=f"fill-{signal.get('signal_id')}",
        kind=kind,
        underlying=str(signal.get("underlying") or contract.get("underlying") or ""),
        expiry=contract.get("expiry") or signal.get("expiry"),
        strike=contract.get("strike") or signal.get("target_strike"),
        option_type=contract.get("option_type") or signal.get("option_type"),
        sleeve=str(signal.get("sleeve") or "fade"),
        lots=order.get("lots") or signal.get("target_lots"),
        filled_qty=order.get("quantity"),
        filled_price=order.get("price"),
        tradingsymbol=str(contract.get("tradingsymbol") or signal.get("symbol") or ""),
        side=side,
    )


def _place_signal(sig: Dict[str, Any], *, side: Optional[str] = None, force_eod: bool = False) -> Dict[str, Any]:
    sid = str(sig.get("signal_id") or "")
    und = str(sig.get("underlying") or "").upper()
    lots = int(sig.get("target_lots") or sig.get("lots") or 1)
    action = str(side or sig.get("action") or "BUY").upper()
    ltp = sig.get("ltp")
    body = SimpleNamespace(
        underlying=und,
        sleeve=str(sig.get("sleeve") or "fade").lower(),
        security_id=sig.get("security_id") or None,
        side=action,
        quantity=None,
        lots=max(1, lots),
        symbol=str(sig.get("symbol") or ""),
        strike=sig.get("target_strike") if sig.get("target_strike") is not None else sig.get("strike"),
        option_type=sig.get("option_type") or "PE",
        expiry=str(sig.get("expiry") or session_day().isoformat()),
        day=session_day().isoformat(),
        tag="edge-desk-auto",
        dry_run=False,
        expected_ltp=ltp,
        price_tolerance=50.0,
        operator_id="auto",
        trace_id=f"auto:{sid}",
        force_session_close=force_eod,
    )
    return place_paper(body, _books())


def tick() -> None:
    """At most one autonomous Dhan place per call. Independent of UI polling."""
    global _eod_done_day
    if (RUNNER.mode or "").lower() not in ("paper", "live"):
        return
    if (RUNNER.execution or "manual").lower() != "auto":
        return
    if not RUNNER.trading_active():
        return
    load_persisted()

    sess = market_session()
    day = session_day().isoformat()

    if sess == "open":
        compass = books.signals_today(_books())
        pending = [s for s in (compass.get("signals") or []) if str(s.get("status") or "").upper() == "PENDING"]
        pending = [s for s in pending if str(s.get("signal_id") or "") not in _fired]
        if pending:
            sig = pending[-1]
            sid = str(sig["signal_id"])
            result = _place_signal(sig)
            code = str(result.get("code") or "")
            if result.get("accepted"):
                _fired.add(sid)
                _save()
                _notice_from_place(sig, result)
                RUNNER.audit_event(
                    "auto.place",
                    signal_id=sid,
                    underlying=str(sig.get("underlying") or ""),
                    code=code,
                    accepted=True,
                )
            elif code in ("GATE_DENY", "SHADOW_HALTED", "KILL_SWITCH", "CONTRACT_RESOLVE_FAILED"):
                _fired.add(sid)
                _save()
                RUNNER.audit_event(
                    "auto.skip",
                    signal_id=sid,
                    underlying=str(sig.get("underlying") or ""),
                    code=code,
                )
        return

    # Auto EOD only in the 15:30 IST square-off window — not on weekends / overnight Start.
    from datetime import datetime
    from app.session import IST

    now = datetime.now(IST)
    if now.weekday() >= 5:
        return
    if not (now.hour == 15 and now.minute >= 30 and now.minute <= 45):
        return
    if _eod_done_day == day:
        return
    try:
        grid = dhan.positions_grid()
    except Exception:
        return
    _eod_done_day = day
    _save()
    n_ok = 0
    for row in list(grid.get("rows") or []):
        qty = int(row.get("qty") or row.get("quantity") or 0)
        if qty <= 0:
            continue
        lots = int(row.get("lots") or 0) or 1
        sig = {
            "signal_id": f"eod-{day}-{row.get('underlying')}-{row.get('symbol')}",
            "underlying": row.get("underlying"),
            "sleeve": str(row.get("sleeve") or "fade"),
            "action": "SELL",
            "target_lots": lots,
            "lots": lots,
            "symbol": row.get("tradingsymbol") or row.get("symbol"),
            "target_strike": row.get("strike"),
            "option_type": row.get("option_type"),
            "expiry": row.get("expiry"),
            "security_id": row.get("security_id"),
            "ltp": row.get("ltp") or row.get("mark_price"),
        }
        result = _place_signal(sig, side="SELL", force_eod=True)
        if result.get("accepted"):
            n_ok += 1
            _notice_from_place(sig, result)
    RUNNER.audit_event("auto.eod", day=day, flattened=n_ok)
