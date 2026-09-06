"""Paper/live auto: dispatch PENDING compass cards to Dhan without UI approval."""
from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

from app import triggers as trigger_store
from app.books import adapters as books
from app.oms import place_paper
from app.mock import MOCK
from app.runners.state import RUNNER
from app.session import market_session, session_day

_STATE = Path(__file__).resolve().parents[1] / "data" / "auto_state.json"
_fired: Set[str] = set()
_eod_done_day: Optional[str] = None
_loaded_day: Optional[str] = None


def _trade_day() -> str:
    if (RUNNER.mode or "").lower() == "mock" and MOCK.loaded:
        return MOCK.clock.day.isoformat()
    return session_day().isoformat()


def _persist_day() -> str:
    """IST calendar day for paper/live auto state — never mock tape day."""
    return session_day().isoformat()


def load_persisted() -> None:
    global _eod_done_day, _loaded_day
    day = _persist_day()
    if _loaded_day == day:
        return
    _fired.clear()
    _eod_done_day = None
    _loaded_day = day
    if not _STATE.exists():
        _save()
        return
    try:
        raw = json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        _save()
        return
    if str(raw.get("day") or "") != day:
        # Roll stale file forward so disk matches the IST session.
        _save()
        return
    _fired.update(str(x) for x in (raw.get("fired") or []))
    _eod_done_day = raw.get("eod_done_day")


def _save() -> None:
    if (RUNNER.mode or "").lower() not in ("paper", "live"):
        return
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(
        json.dumps(
            {
                "day": _persist_day(),
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
    return books.desk_books()


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
        expiry=sig.get("expiry") or None,
        day=_trade_day(),
        tag="edge-desk-auto",
        dry_run=False,
        expected_ltp=ltp,
        price_tolerance=50.0,
        operator_id="auto",
        trace_id=f"auto:{sid}",
        force_session_close=force_eod,
        pack_id=str(sig.get("pack_id") or "") or None,
    )
    return place_paper(body, _books())


def _session_now():
    if (RUNNER.mode or "").lower() == "mock" and MOCK.loaded:
        return MOCK.clock.now(), MOCK.clock.market_session()
    from datetime import datetime
    from app.session import IST

    now = datetime.now(IST)
    return now, market_session()


def _compass() -> Dict[str, Any]:
    if (RUNNER.mode or "").lower() == "mock" and MOCK.loaded:
        return MOCK.ledger.signals_today()
    return books.signals_today(_books())


def _positions() -> Dict[str, Any]:
    if (RUNNER.mode or "").lower() == "mock" and MOCK.loaded:
        return MOCK.ledger.positions_grid()
    from app import paper_oms

    return paper_oms.desk_positions(_books())


def _signal_due(sig: Dict[str, Any], now) -> bool:
    created = sig.get("created_at")
    if not created:
        return True
    try:
        from datetime import datetime as _dt

        dt = _dt.fromisoformat(str(created).replace("Z", "+00:00"))
        return now >= dt
    except Exception:
        return True


def tick() -> None:
    """At most one autonomous place per call — mock, paper, and live."""
    global _eod_done_day
    mode = (RUNNER.mode or "").lower()
    if mode not in ("paper", "live", "mock"):
        return
    if mode == "live":
        from app.auth import get_settings

        s = get_settings()
        if not (s.live_enabled and s.live_nifty and s.live_banknifty):
            return
    if (RUNNER.execution or "manual").lower() != "auto":
        return
    if not RUNNER.trading_active():
        return
    if mode == "mock" and not MOCK.loaded:
        return
    load_persisted()

    now, sess = _session_now()
    day = session_day().isoformat() if mode != "mock" else (MOCK.clock.day.isoformat() if MOCK.loaded else session_day().isoformat())

    if sess == "open":
        compass = _compass()
        pending = [s for s in (compass.get("signals") or []) if str(s.get("status") or "").upper() == "PENDING"]
        pending = [s for s in pending if str(s.get("signal_id") or "") not in _fired]
        pending = [s for s in pending if _signal_due(s, now)]
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

    if now.weekday() >= 5:
        return
    if not (now.hour == 15 and now.minute >= 30 and now.minute <= 45):
        return
    if _eod_done_day == day:
        return
    try:
        grid = _positions()
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
            "signal_id": f"eod-{day}-{row.get('pack_id') or row.get('underlying')}-{row.get('symbol')}",
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
            "pack_id": row.get("pack_id"),
        }
        result = _place_signal(sig, side="SELL", force_eod=True)
        if result.get("accepted"):
            n_ok += 1
            _notice_from_place(sig, result)
    RUNNER.audit_event("auto.eod", day=day, flattened=n_ok)
    try:
        from app import paper_archive

        paper_archive.capture(reason="auto_eod")
    except Exception:
        pass
    if n_ok:
        try:
            from app.desk_events import emit_position_remove, emit_position_upsert

            grid = _positions()
            for row in list(grid.get("rows") or []):
                qty = int(row.get("qty") or row.get("quantity") or 0)
                if qty != 0:
                    emit_position_upsert(row)
                else:
                    emit_position_remove(row)
        except Exception:
            pass
