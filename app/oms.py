"""Paper place / cancel — UI is the only caller. Engine must never invoke this."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from app import idempotency
from app.books import adapters as books
from app.books import shadow_oms
from app.brokers.dhan import client as dhan
from app.brokers.dhan.contracts import exchange_qty, resolve_contract
from app.mock import MOCK
from app.runners.state import RUNNER, _now
from app.session import market_session, session_day


def dhan_correlation_id(trace_id: Any, client_oid: str) -> str:
    """Map OMS trace_id onto Dhan correlationId (alnum, max 50)."""
    raw = str(trace_id or client_oid or "").strip() or client_oid
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in ("-", "_"))
    if not cleaned:
        cleaned = str(client_oid)
    return cleaned[:50]


def _audit_dir():
    from app.auth import get_settings

    return get_settings().audit_dir


def _persist_order(payload: Dict[str, Any]) -> None:
    audit_dir = _audit_dir()
    audit_dir.mkdir(parents=True, exist_ok=True)
    day_u = session_day().isoformat()
    with (audit_dir / f"orders_{day_u}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _now(), **payload}, default=str) + "\n")


def _gate_payload(gate: Dict[str, Any], sleeve: str) -> Dict[str, Any]:
    reason = gate.get("reason")
    if reason in ("", "ok", "OK"):
        reason = None
    return {
        "allow": bool(gate.get("allow")),
        "lots": int(gate.get("lots") or 0),
        "reason": reason,
        "sleeve": sleeve.lower(),
    }


def _contract_ui(contract, *, lots: int, quantity: int) -> Dict[str, Any]:
    d = contract.as_dict()
    d["lots"] = lots
    d["quantity"] = quantity
    return d


def _quote_ui(q: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not q:
        return None
    return {
        "ltp": q.get("ltp"),
        "bid": q.get("bid"),
        "ask": q.get("ask"),
        "quoted_at": q.get("quoted_at"),
    }


def _estimate(ltp: Optional[float], quantity: int) -> Dict[str, Any]:
    prem = round(float(ltp or 0) * int(quantity), 2)
    est_costs = round(max(20.0, prem * 0.004) + 20.0, 2)
    return {"premium_value": prem, "est_costs": est_costs, "notional": prem}


def _live_quote(security_id: str) -> Optional[Dict[str, Any]]:
    try:
        return dhan.market_quote_option(str(security_id))
    except Exception:
        return None


def _reject(code: str, message: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = {"accepted": False, "code": code, "message": message}
    if extra:
        data.update(extra)
    return data


def classify_broker_error(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "timed out" in msg or "timeout" in msg or "http 5" in msg or "unreachable" in msg:
        return "BROKER_UNREACHABLE"
    return "BROKER_REJECT"


def classify_cancel_error(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "not found" in msg or "http 404" in msg:
        return "ORDER_NOT_FOUND"
    if "traded" in msg or "filled" in msg or "complete" in msg:
        return "ALREADY_FILLED"
    if "timed out" in msg or "timeout" in msg or "http 5" in msg:
        return "BROKER_UNREACHABLE"
    return "BROKER_REJECT"


def _mock_contract(und: str, body: Any, ev: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    from app.brokers.dhan.contracts import DEFAULT_LOT

    lot = int((ev or {}).get("lot_size") or DEFAULT_LOT.get(und, 65))
    strike = float(getattr(body, "strike", None) or (ev or {}).get("strike") or 0)
    opt = str(getattr(body, "option_type", None) or (ev or {}).get("option_type") or "PE").upper()
    expiry = str(getattr(body, "expiry", None) or (ev or {}).get("expiry") or MOCK.clock.day.isoformat())
    symbol = str(getattr(body, "symbol", None) or (ev or {}).get("symbol") or f"{und}{int(strike)}{opt}")
    sid = str(getattr(body, "security_id", None) or (ev or {}).get("security_id") or f"mock-{und}-{int(strike)}-{opt}")
    lots = int(getattr(body, "lots", None) or (ev or {}).get("lots") or 1)
    qty = lots * lot
    return {
        "underlying": und,
        "security_id": sid,
        "tradingsymbol": symbol,
        "strike": strike,
        "option_type": opt,
        "expiry": expiry,
        "lot_size": lot,
        "lots": lots,
        "quantity": qty,
        "symbol": symbol,
    }


def _place_mock(body: Any, *, dry_run: bool, sleeve: str, und: str, side: str, operator_id: str, trace_id: Any) -> Dict[str, Any]:
    MOCK.tick()
    if not MOCK.loaded:
        return _reject("BROKER_UNREACHABLE", "Mock replay is not loaded. Start with mode mock.")
    ev = MOCK.match_event(underlying=und, strike=float(getattr(body, "strike", 0) or 0), option_type=str(getattr(body, "option_type") or ""))
    cui = _mock_contract(und, body, ev)
    gate_list = MOCK.gates(und)["sleeves"]
    gate = next((g for g in gate_list if g["sleeve"] == sleeve), gate_list[0] if gate_list else {"allow": True, "lots": cui["lots"], "reason": None, "sleeve": sleeve})
    gate = {**gate, "sleeve": sleeve}
    q = MOCK.quote_option(
        security_id=cui["security_id"],
        underlying=und,
        expiry=cui["expiry"],
        strike=cui["strike"],
        option_type=cui["option_type"],
    )
    quote = {"ltp": q.get("ltp"), "bid": q.get("bid"), "ask": q.get("ask"), "quoted_at": q.get("quoted_at")}
    estimate = _estimate(q.get("ltp"), cui["quantity"])
    if not gate.get("allow"):
        return _reject("GATE_DENY", gate.get("reason") or "Sleeve blocked today.", {"gate": gate, "contract": cui, "quote": quote, "estimate": estimate})
    if int(cui["lots"]) > int(gate.get("lots") or 0) > 0:
        return _reject(
            "GATE_DENY",
            f"Requested {cui['lots']} lots exceeds gate max {gate.get('lots')}.",
            {"gate": gate, "contract": cui, "quote": quote},
        )
    if dry_run:
        return {
            "accepted": True,
            "code": "OK",
            "message": "simulated only (dry_run)",
            "gate": gate,
            "quote": quote,
            "contract": cui,
            "estimate": estimate,
        }
    expected = getattr(body, "expected_ltp", None)
    live_ltp = q.get("ltp")
    if expected is None:
        return _reject("PRICE_MOVED", "expected_ltp is required to place.", {"contract": cui, "lots": cui["lots"]})
    if live_ltp is None:
        return _reject("BROKER_UNREACHABLE", "Could not refresh live LTP. Nothing was placed.", {"contract": cui, "gate": gate})
    tolerance = float(getattr(body, "price_tolerance", None) or 0.5)
    if abs(float(live_ltp) - float(expected)) > tolerance:
        qty = cui["quantity"]
        return {
            "accepted": False,
            "code": "PRICE_MOVED",
            "message": "Live price changed before send. Nothing was placed.",
            "side": side,
            "was": {"ltp": float(expected), "value": round(float(expected) * qty, 2)},
            "now": {"ltp": float(live_ltp), "value": round(float(live_ltp) * qty, 2)},
            "contract": cui,
            "lots": cui["lots"],
            "lot_size": cui["lot_size"],
            "quote": quote,
        }
    client_oid = f"paper-{uuid4().hex[:12]}"
    origin = "overlay"
    if MOCK.execution == "manual" and ev and side == "BUY":
        st = MOCK.ledger.signal_status(ev["signal_id"])
        if st == "PENDING":
            origin = "tape"
    if side == "SELL":
        try:
            rec = MOCK.ledger.sell(
                underlying=und,
                symbol=cui["symbol"],
                lots=cui["lots"],
                lot_size=cui["lot_size"],
                price=float(live_ltp),
                client_order_id=client_oid,
                reason="overlay",
                close_source="user",
            )
        except RuntimeError as exc:
            return _reject("BROKER_REJECT", str(exc), {"contract": cui, "gate": gate, "quote": quote})
    else:
        rec = MOCK.ledger.open_buy(
            ev=ev,
            underlying=und,
            symbol=cui["symbol"],
            security_id=cui["security_id"],
            expiry=cui["expiry"],
            strike=cui["strike"],
            option_type=cui["option_type"],
            sleeve=sleeve,
            lots=cui["lots"],
            lot_size=cui["lot_size"],
            price=float(live_ltp),
            client_order_id=client_oid,
            origin=origin,
            tape_signal_id=(ev or {}).get("signal_id") if origin == "tape" else None,
            tape_exit_reason=(ev or {}).get("exit_reason") if origin == "tape" else None,
            tape_exit_px=(ev or {}).get("exit") if origin == "tape" else None,
            event_id=(ev or {}).get("signal_id") if origin == "tape" else None,
        )
        if ev and origin == "tape":
            MOCK.ledger.set_signal(ev["signal_id"], "EXECUTED", "manual")
    RUNNER.orders_executed += 1
    RUNNER.audit_event("order.paper_place", mode="mock", operator_id=operator_id, trace_id=trace_id, client_order_id=client_oid)
    broker_oid = rec.get("broker_order_id") or rec.get("client_order_id")
    if (MOCK.execution or "").lower() == "auto":
        from app import triggers as trigger_store

        kind = "sell" if side == "SELL" else "buy"
        trigger_store.push_fill_notice(
            trigger_id=f"fill-mock-{client_oid}",
            kind=kind,
            underlying=und,
            expiry=cui.get("expiry"),
            strike=cui.get("strike"),
            option_type=cui.get("option_type"),
            sleeve=sleeve,
            lots=cui["lots"],
            filled_qty=rec.get("quantity") or cui["quantity"],
            filled_price=float(live_ltp),
            tradingsymbol=str(cui.get("tradingsymbol") or cui.get("symbol") or ""),
            side=side,
        )
    return {
        "accepted": True,
        "code": "OK",
        "message": None,
        "order": {
            "client_order_id": client_oid,
            "broker_order_id": broker_oid,
            "side": side,
            "lots": cui["lots"],
            "lot_size": cui["lot_size"],
            "quantity": rec.get("quantity") or cui["quantity"],
            "price": float(live_ltp),
            "status": "TRANSIT",
        },
        "contract": cui,
        "gate": gate,
        "quote": quote,
    }


def place_paper(body: Any, book_list) -> Dict[str, Any]:
    dry_run = bool(getattr(body, "dry_run", False))
    sleeve = str(getattr(body, "sleeve", None) or "fade").lower()
    und = str(getattr(body, "underlying", "") or "").upper()
    side = str(getattr(body, "side", "BUY") or "BUY").upper()
    operator_id = str(getattr(body, "operator_id", None) or "ui")
    trace_id = getattr(body, "trace_id", None)

    if not dry_run and trace_id:
        cached = idempotency.get(str(trace_id))
        if cached is not None:
            return cached

    def finish(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not dry_run and trace_id:
            idempotency.put(str(trace_id), payload)
        return payload

    if RUNNER.kill.active and not dry_run:
        return finish(_reject("KILL_SWITCH", "Kill switch is on. Nothing was placed."))

    if not dry_run and not RUNNER.trading_active():
        return finish(
            _reject(
                "TRADING_STOPPED",
                "Start trading first. Place stays off until paper is armed.",
            )
        )

    sess = MOCK.clock.market_session() if (RUNNER.mode or "").lower() == "mock" and MOCK.loaded else market_session()
    force_eod = bool(getattr(body, "force_session_close", False)) and operator_id == "auto"
    if not dry_run and sess != "open" and not force_eod:
        return finish(_reject("MARKET_CLOSED", "NSE cash session is closed. Nothing was placed."))

    if und not in ("NIFTY", "BANKNIFTY"):
        return finish(_reject("CONTRACT_RESOLVE_FAILED", f"unknown underlying {und}"))

    if (RUNNER.mode or "").lower() == "mock":
        return finish(_place_mock(body, dry_run=dry_run, sleeve=sleeve, und=und, side=side, operator_id=operator_id, trace_id=trace_id))

    book = books.book_by_underlying(book_list, und)
    if book is None:
        return finish(_reject("CONTRACT_RESOLVE_FAILED", f"unknown underlying {und}"))

    if books.book_is_halted(book) and not dry_run:
        return finish(
            _reject(
                "SHADOW_HALTED",
                f"{und} book is halted. Nothing was placed.",
                {"underlying": und},
            )
        )

    gate_raw = books.check_book_gate(book, sleeve=sleeve)
    gate = _gate_payload(gate_raw, sleeve)

    day = str(getattr(body, "day", None) or session_day().isoformat())
    contract = None
    try:
        contract = resolve_contract(
            underlying=und,
            strike=getattr(body, "strike", None),
            option_type=getattr(body, "option_type", None),
            symbol=getattr(body, "symbol", None) or "",
            security_id=getattr(body, "security_id", None),
            expiry=getattr(body, "expiry", None),
            session_day=session_day(),
        )
    except Exception as exc:  # noqa: BLE001
        extra: Dict[str, Any] = {"gate": gate}
        if not gate["allow"]:
            return finish(
                _reject("GATE_DENY", gate["reason"] or "Sleeve blocked.", extra)
            )
        return finish(
            _reject(
                "CONTRACT_RESOLVE_FAILED",
                f"Unknown expiry/strike. Nothing was placed. ({exc})",
                extra,
            )
        )

    lots_in = getattr(body, "lots", None)
    if lots_in is None:
        lots_in = int(gate.get("lots") or 1)
    try:
        qty, lots_i, lot_size = exchange_qty(
            lots=int(lots_in),
            lot_size=contract.lot_size,
            quantity=None if getattr(body, "lots", None) is not None else getattr(body, "quantity", None),
            prefer_lots=getattr(body, "lots", None) is not None,
        )
    except Exception as exc:  # noqa: BLE001
        return finish(_reject("CONTRACT_RESOLVE_FAILED", str(exc), {"gate": gate, "contract": contract.as_dict()}))

    cui = _contract_ui(contract, lots=lots_i, quantity=qty)
    quote = _live_quote(contract.security_id)
    estimate = _estimate((quote or {}).get("ltp"), qty)

    if not gate["allow"]:
        RUNNER.audit_event("order.paper_denied", underlying=und, sleeve=sleeve, reason=gate.get("reason"), operator_id=operator_id, trace_id=trace_id)
        return finish(
            _reject(
                "GATE_DENY",
                gate.get("reason") or "Sleeve blocked today.",
                {"gate": gate, "contract": cui, "quote": _quote_ui(quote), "estimate": estimate},
            )
        )

    if qty <= 0:
        return finish(_reject("GATE_DENY", "quantity/lots is zero", {"gate": gate, "contract": cui}))

    if lots_i > int(gate.get("lots") or 0) > 0:
        return finish(
            _reject(
                "GATE_DENY",
                f"Requested {lots_i} lots exceeds gate max {gate.get('lots')}.",
                {"gate": gate, "contract": cui, "quote": _quote_ui(quote)},
            )
        )

    if dry_run:
        RUNNER.audit_event("order.paper_preview", underlying=und, sleeve=sleeve, lots=lots_i, operator_id=operator_id, trace_id=trace_id)
        return {
            "accepted": True,
            "code": "OK",
            "message": "simulated only (dry_run)",
            "gate": gate,
            "quote": _quote_ui(quote) or {"ltp": None, "bid": None, "ask": None, "quoted_at": _now()},
            "contract": cui,
            "estimate": estimate,
        }

    expected = getattr(body, "expected_ltp", None)
    auto_send = operator_id == "auto" or str(trace_id or "").startswith("auto:")
    if expected is None and auto_send:
        expected = (quote or {}).get("ltp")
    if expected is None:
        return finish(_reject("PRICE_MOVED", "expected_ltp is required to place.", {"contract": cui, "lots": lots_i}))

    tolerance = float(getattr(body, "price_tolerance", None) or 0.5)
    live_ltp = (quote or {}).get("ltp")
    if live_ltp is None:
        return finish(
            _reject(
                "BROKER_UNREACHABLE",
                "Could not refresh live LTP. Nothing was placed.",
                {"contract": cui, "gate": gate},
            )
        )
    if auto_send:
        expected = live_ltp
    if abs(float(live_ltp) - float(expected)) > tolerance:
        was_val = round(float(expected) * qty, 2)
        now_val = round(float(live_ltp) * qty, 2)
        return finish(
            {
                "accepted": False,
                "code": "PRICE_MOVED",
                "message": "Live price changed before send. Nothing was placed.",
                "side": side,
                "was": {"ltp": float(expected), "value": was_val},
                "now": {"ltp": float(live_ltp), "value": now_val},
                "contract": cui,
                "lots": lots_i,
                "lot_size": lot_size,
                "quote": _quote_ui(quote),
            }
        )

    client_oid = f"paper-{uuid4().hex[:12]}"
    corr_id = dhan_correlation_id(trace_id, client_oid)
    tag = getattr(body, "tag", None) or ("edge-desk-live" if (RUNNER.mode or "").lower() == "live" else "edge-desk-paper")
    order_rec = {
        "client_order_id": client_oid,
        "correlation_id": corr_id,
        "underlying": und,
        "sleeve": sleeve,
        "security_id": contract.security_id,
        "symbol": contract.tradingsymbol,
        "side": side,
        "quantity": qty,
        "lots": lots_i,
        "lot_size": lot_size,
        "tag": tag,
        "mode": RUNNER.mode,
        "queued_at": _now(),
        "trace_id": trace_id,
        "day": day,
        "operator_id": operator_id,
    }
    RUNNER.audit_event(
        "order.paper_place",
        operator_id=operator_id,
        trace_id=trace_id,
        **{k: v for k, v in order_rec.items() if k not in ("gate", "contract")},
    )

    try:
        raw = dhan.place_order(
            security_id=contract.security_id,
            transaction_type=side,
            quantity=qty,
            tag=order_rec["tag"] or "edge-desk",
            correlation_id=corr_id,
        )
        broker_id = None
        raw_inner = raw.get("raw") if isinstance(raw, dict) else None
        if isinstance(raw_inner, dict):
            broker_id = raw_inner.get("orderId") or raw_inner.get("order_id")
            data = raw_inner.get("data")
            if isinstance(data, dict):
                broker_id = broker_id or data.get("orderId")
        RUNNER.orders_executed += 1
        RUNNER.audit_event("order.submitted", client_order_id=client_oid, operator_id=operator_id, trace_id=trace_id)
        _persist_order({**order_rec, "state": "submitted", "broker": raw})
        try:
            shadow_oms.record_broker_order(
                book,
                day=day,
                sleeve=sleeve,
                order={**order_rec, "state": "submitted", "broker": raw},
                contract=contract.as_dict(),
            )
        except Exception as shadow_exc:  # noqa: BLE001
            RUNNER.audit_event("shadow.persist_failed", error=str(shadow_exc)[:240], client_order_id=client_oid)
        try:
            from app import paper_archive

            paper_archive.capture(reason="order_place")
        except Exception:
            pass
        placed = {
            "accepted": True,
            "code": "OK",
            "message": None,
            "order": {
                "client_order_id": client_oid,
                "broker_order_id": str(broker_id) if broker_id else None,
                "order_id": str(broker_id) if broker_id else client_oid,
                "side": side,
                "lots": lots_i,
                "lot_size": lot_size,
                "quantity": qty,
                "price": float(live_ltp),
                "status": "TRANSIT",
            },
            "contract": cui,
            "gate": gate,
            "quote": _quote_ui(quote),
        }
        try:
            from app.desk_events import emit_paper_place_result

            pos_row = None
            try:
                grid = dhan.positions_grid()
                sid = str(contract.security_id)
                for row in list(grid.get("rows") or []):
                    if str(row.get("security_id") or "") == sid:
                        pos_row = row
                        break
            except Exception:
                pos_row = None
            emit_paper_place_result(placed, positions_row=pos_row)
        except Exception:
            pass
        return finish(placed)
    except Exception as exc:  # noqa: BLE001
        code = classify_broker_error(exc)
        RUNNER.last_error = str(exc)[:240]
        RUNNER.audit_event("order.error", error=str(exc)[:240], client_order_id=client_oid, operator_id=operator_id)
        _persist_order({**order_rec, "state": "error", "error": str(exc)})
        return finish(
            _reject(
                code,
                "Broker refused the order. Nothing was confirmed."
                if code == "BROKER_REJECT"
                else "Broker unreachable. Nothing was placed.",
                {
                    "order": {
                        "client_order_id": client_oid,
                        "broker_order_id": None,
                        "side": side,
                        "lots": lots_i,
                        "lot_size": lot_size,
                        "quantity": qty,
                        "price": float(live_ltp) if live_ltp is not None else None,
                        "status": "REJECTED",
                    },
                    "contract": cui,
                    "gate": gate,
                    "quote": _quote_ui(quote),
                },
            )
        )


def cancel_paper(order_id: str, operator_id: str = "ui") -> Dict[str, Any]:
    oid = str(order_id or "").strip()
    base = {"order_id": oid}
    if RUNNER.kill.active:
        return {**base, "accepted": False, "code": "KILL_SWITCH", "message": "Kill switch is on. Order was not cancelled."}
    if not oid:
        return {**base, "accepted": False, "code": "ORDER_NOT_FOUND", "message": "order_id is required."}
    if (RUNNER.mode or "").lower() == "mock" and MOCK.loaded:
        RUNNER.audit_event("order.cancel", order_id=oid, operator_id=operator_id, mode="mock")
        return MOCK.ledger.cancel(oid)
    try:
        raw = dhan.cancel_order(oid)
        RUNNER.audit_event("order.cancel", order_id=oid, operator_id=operator_id)
        status = ""
        if isinstance(raw, dict):
            inner = raw.get("raw") if isinstance(raw.get("raw"), dict) else raw
            status = str((inner or {}).get("orderStatus") or (inner or {}).get("status") or "")
        st = status.upper()
        if st in ("TRADED", "TRADE", "FILLED", "COMPLETE"):
            return {
                **base,
                "accepted": False,
                "code": "ALREADY_FILLED",
                "message": "Order already filled. Check Active trades.",
            }
        try:
            from app.desk_events import emit_order_remove

            emit_order_remove(oid)
        except Exception:
            pass
        return {**base, "accepted": True, "code": "OK", "message": None, "result": raw}
    except Exception as exc:  # noqa: BLE001
        code = classify_cancel_error(exc)
        messages = {
            "ALREADY_FILLED": "Order already filled. Check Active trades.",
            "ORDER_NOT_FOUND": "Order not found. Nothing was cancelled.",
            "BROKER_UNREACHABLE": "Broker unreachable. Order was not cancelled.",
            "BROKER_REJECT": "Broker refused the cancel.",
        }
        RUNNER.audit_event("order.cancel_error", order_id=oid, operator_id=operator_id, error=str(exc)[:240])
        return {**base, "accepted": False, "code": code, "message": messages.get(code, str(exc)[:240])}
