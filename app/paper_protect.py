"""Paper YAML exits (stop / TP / trail) + journal write-back. No Dhan money."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app import paper_oms
from app.books import adapters as books
from app.books import shadow_oms
from app.session import session_day


def _book_for(und: str, pack_id: str = ""):
    return books.book_for_place(books.desk_books(), und, pack_id)


def _journal_exit(sold: Dict[str, Any]) -> None:
    und = str(sold.get("underlying") or "")
    book = _book_for(und, str(sold.get("pack_id") or ""))
    if book is None:
        return
    day = session_day().isoformat()
    sleeve = str(sold.get("sleeve") or "fade")
    order = sold.get("order") or {}
    contract = {
        "security_id": sold.get("security_id"),
        "tradingsymbol": sold.get("symbol") or order.get("symbol"),
        "strike": sold.get("strike"),
        "option_type": sold.get("option_type"),
        "lot_size": sold.get("lot_size") or order.get("lot_size"),
        "expiry": sold.get("expiry"),
    }
    try:
        shadow_oms.record_broker_order(
            book,
            day=day,
            sleeve=sleeve,
            order={**order, "state": "TRADED", "side": "SELL"},
            contract=contract,
        )
        shadow_oms.record_entry_fill(
            book,
            day=day,
            sleeve=sleeve,
            entry=float(sold.get("entry_avg") or 0),
            qty=int(sold.get("sold_qty") or 0),
            notes=f"desk_paper_{sold.get('reason') or 'exit'}",
            source="desk_paper",
            exit_px=float(sold.get("exit_price") or 0),
            net_pnl=float(sold.get("realized_pnl") or 0),
        )
    except Exception:
        pass


def _ensure_yaml_recipe(pos: Dict[str, Any]) -> None:
    if not pos or float(pos.get("stop_pct") or 0.0) > 0:
        return
    book = _book_for(str(pos.get("underlying") or ""), str(pos.get("pack_id") or ""))
    if book is None:
        return
    sleeve = str(pos.get("sleeve") or "fade")
    stop_pct, tp_pct = books.sleeve_risk_params(book, sleeve)
    trail_pct, act = books.sleeve_trail_params(book, sleeve)
    key = str(pos.get("ledger_key") or pos.get("security_id") or "")
    paper_oms.ensure_recipe(
        key,
        stop_pct=stop_pct,
        tp_pct=tp_pct,
        trail_pct=trail_pct,
        trail_activate_pct=act,
        pack_id=str(pos.get("pack_id") or ""),
    )


def on_mark(security_id: str, ltp: float) -> Optional[Dict[str, Any]]:
    sid = str(security_id)
    last: Optional[Dict[str, Any]] = None
    for key in paper_oms.keys_for_security_id(sid):
        pid = key.split("::", 1)[0] if "::" in key else ""
        pos = paper_oms.peek(sid, pack_id=pid)
        if not pos:
            continue
        _ensure_yaml_recipe(pos)
        sold = paper_oms.mark_and_maybe_exit(
            str(pos.get("security_id") or sid),
            float(ltp),
            pack_id=str(pos.get("pack_id") or ""),
        )
        if not sold or not sold.get("ok"):
            continue
        _journal_exit(sold)
        last = sold
        remaining = paper_oms.peek(str(sold.get("security_id") or sid), pack_id=str(sold.get("pack_id") or ""))
        if remaining and int(remaining.get("qty") or 0) > 0:
            pos_row = remaining
        else:
            pos_row = {
                "security_id": sold.get("security_id") or sid,
                "qty": 0,
                "quantity": 0,
                "underlying": sold.get("underlying"),
                "symbol": sold.get("symbol"),
                "pack_id": sold.get("pack_id"),
            }
        try:
            from app.desk_events import emit_paper_place_result

            emit_paper_place_result(
                {
                    "accepted": True,
                    "order": {
                        **(sold.get("order") or {}),
                        "status": "TRADED",
                        "order_id": sold.get("broker_order_id"),
                    },
                },
                positions_row=pos_row,
            )
        except Exception:
            pass
    return last
