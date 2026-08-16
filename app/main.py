"""Options Edge Desk FastAPI — UI contract for my-options-trader."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import get_settings, require_api_key, require_ws_api_key
from app.books import adapters as books
from app.brokers.dhan import client as dhan
from app.brokers.dhan.contracts import chain_snapshot, default_lot_size, resolve_contract
from app.mock import MOCK
from app.oms import cancel_paper, place_paper
from app.research import stable as research_stable
from app.runners.state import RUNNER, _now
from app.schemas.envelope import err, ok
from app.session import market_session, session_day
from app import triggers as trigger_store


def _mock_on() -> bool:
    return (RUNNER.mode or "").lower() == "mock" and MOCK.loaded


async def _token_keeper() -> None:
    """Renew Dhan token while still valid; optional TOTP regen if configured."""
    while True:
        try:
            result = await asyncio.to_thread(dhan.ensure_fresh_token)
            if result.get("action") in ("renewed", "generated_totp"):
                RUNNER.audit_event("token.auto", **{k: v for k, v in result.items() if k != "raw_keys"})
            elif result.get("action") == "needs_manual":
                RUNNER.last_error = f"Dhan token needs refresh: {result.get('detail')}"
        except Exception as exc:  # noqa: BLE001
            RUNNER.audit_event("token.auto_error", error=str(exc))
        await asyncio.sleep(15 * 60)


async def _mock_keeper() -> None:
    """Active sim clock: evaluate fills/exits even if the UI is not polling."""
    from app.mock import MOCK

    while True:
        try:
            if (RUNNER.mode or "").lower() == "mock" and RUNNER.trading_active() and MOCK.loaded:
                await MOCK.exclusive(MOCK.tick)
        except Exception:
            pass
        await asyncio.sleep(0.25)


async def _broker_auto_keeper() -> None:
    """Paper/live auto: place PENDING signals on Dhan without UI polling."""
    from app import auto_engine

    while True:
        try:
            if (RUNNER.mode or "").lower() in ("paper", "live") and (RUNNER.execution or "").lower() == "auto":
                if RUNNER.trading_active():
                    await asyncio.to_thread(auto_engine.tick)
        except Exception:
            pass
        await asyncio.sleep(1.0)


async def _paper_session_keeper() -> None:
    """Weekday paper-auto: arm ~09:10 IST, run cash session, disarm after 15:45."""
    from app import schedule

    while True:
        try:
            await asyncio.to_thread(schedule.tick)
        except Exception:
            pass
        await asyncio.sleep(5.0)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    dhan.load_dotenv()
    get_settings()
    RUNNER.load()
    MOCK.bind_loop(asyncio.get_running_loop())
    token_task = asyncio.create_task(_token_keeper())
    mock_task = asyncio.create_task(_mock_keeper())
    auto_task = asyncio.create_task(_broker_auto_keeper())
    sched_task = asyncio.create_task(_paper_session_keeper())
    try:
        await asyncio.to_thread(dhan.ensure_fresh_token)
    except Exception:
        pass
    yield
    for task in (token_task, mock_task, auto_task, sched_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Options Edge Desk", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request, exc: StarletteHTTPException):
    code = "unauthorized" if exc.status_code == 401 else "error"
    detail = exc.detail if isinstance(exc.detail, str) else "request failed"
    if exc.status_code == 401:
        detail = "invalid or missing API key"
    return JSONResponse(status_code=exc.status_code, content=err(detail, code=code))


@app.exception_handler(RequestValidationError)
async def validation_handler(_request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content=err(str(exc.errors()), code="invalid_request"))


def _books() -> List[books.BookPaths]:
    s = get_settings()
    return [
        books.nifty_book(s.nifty_lab_root, s.nifty_config),
        books.bn_book(s.bn_lab_root, s.bn_config),
    ]


def _active_trigger() -> Dict[str, Any]:
    acked = trigger_store.acked_ids()
    fill = trigger_store.newest_fill(acked)
    if fill.get("active"):
        return fill
    if (RUNNER.execution or "manual").lower() == "auto":
        return {"active": False, "trigger": None}
    if _mock_on():
        return MOCK.triggers_active(acked)
    compass = books.signals_today(_books())
    shadow = books.shadow_book_status(_books())
    return trigger_store.newest_pending(
        compass.get("signals") or [],
        trading_active=RUNNER.trading_active(),
        kill_switch_active=bool(RUNNER.kill.active),
        halted_underlyings=list(shadow.get("halted_underlyings") or []),
    )


def _token_ok() -> bool:
    try:
        return bool(dhan.token_status().get("token_ok"))
    except Exception:
        return False


def _spots_safe() -> Dict[str, Optional[float]]:
    try:
        return dhan.spots()
    except Exception:
        return {"NIFTY": None, "BANKNIFTY": None, "nifty_spot": None, "banknifty_spot": None}


def health_tick_payload() -> Dict[str, Any]:
    data = {k: v for k, v in desk_status_payload().items() if k in (
        "desk_process",
        "trading_active",
        "runner_state",
        "mode",
        "token_ok",
        "kill_switch_active",
        "shadow_book_halted",
        "halted_underlyings",
        "broker_reachable",
        "market_session",
        "nifty_spot",
        "banknifty_spot",
        "today_net",
        "open_positions",
        "execution",
        "replay",
        "paper_auto",
        "last_error",
    )}
    trig = _active_trigger()
    data["trigger"] = trig
    return data


def desk_status_payload() -> Dict[str, Any]:
    """Flat MVP snapshot — Home banners, tape, books."""
    mode = (RUNNER.mode or "paper").lower()
    if mode not in ("paper", "live", "mock"):
        mode = "paper"
    last_err = RUNNER.last_error
    if last_err and ("Traceback" in last_err or len(last_err) > 240):
        last_err = last_err.split("\n")[0][:240]
    base = {
        "desk_process": "alive",
        "trading_active": RUNNER.trading_active(),
        "runner_state": RUNNER.state,
        "mode": mode,
        "kill_switch_active": bool(RUNNER.kill.active),
        "last_error": last_err,
        "last_cycle_at": RUNNER.last_cycle_at,
        "execution": RUNNER.execution,
        "replay": MOCK.replay() if mode == "mock" and MOCK.loaded else None,
    }
    if mode == "mock" and MOCK.loaded:
        extra = MOCK.status_fields()
        return {**base, **extra, "mode": "mock"}

    spots = {"NIFTY": {"ltp": None, "change_pct": None}, "BANKNIFTY": {"ltp": None, "change_pct": None}}
    try:
        spots = dhan.spots_with_change()
    except Exception:
        pass
    shadow = books.shadow_book_status(_books())
    cash = None
    broker_ok = dhan.broker_reachable()
    try:
        cash = dhan.available_cash()
        broker_ok = True
    except Exception:
        broker_ok = False
    pos_rows: List[dict] = []
    try:
        pos = dhan.positions_grid()
        pos_rows = list(pos.get("rows") or [])
    except Exception:
        pos_rows = []
        broker_ok = False
    unreal = round(sum(float(r.get("unrealized_pnl") or 0) for r in pos_rows), 2)
    blotter = books.trades_today(_books())
    compass = books.signals_today(_books())
    realized = float(blotter.get("total_realized_pnl") or 0)
    today_net = round(realized + unreal, 2)
    book_rows = books.books_snapshot(_books(), position_rows=pos_rows)
    from app.desk_log import count_today
    from app.schedule import schedule_wanted

    return {
        **base,
        "token_ok": _token_ok(),
        "shadow_book_halted": bool(shadow.get("halted")),
        "halted_underlyings": list(shadow.get("halted_underlyings") or []),
        "broker_reachable": bool(broker_ok),
        "market_session": market_session(),
        "session_label": "NSE 09:15–15:30 IST",
        "available_cash": cash,
        "nifty_spot": (spots.get("NIFTY") or {}).get("ltp"),
        "nifty_change_pct": (spots.get("NIFTY") or {}).get("change_pct"),
        "banknifty_spot": (spots.get("BANKNIFTY") or {}).get("ltp"),
        "banknifty_change_pct": (spots.get("BANKNIFTY") or {}).get("change_pct"),
        "open_positions": len(pos_rows),
        "realized_pnl_today": realized,
        "unrealized_pnl": unreal,
        "today_net": today_net,
        "last_sync_at": RUNNER.last_sync_at,
        "books": book_rows,
        "paper_auto": bool(schedule_wanted() and (RUNNER.execution or "") == "auto"),
        "signals_today": int(compass.get("count") or 0),
        "trades_today": int(blotter.get("trade_count") or 0),
        "log_events_today": count_today(),
    }


def health_full_payload() -> Dict[str, Any]:
    spots = _spots_safe()
    shadow = books.shadow_book_status(_books())
    circuit = books.circuit_from_books(_books())
    cash = None
    try:
        cash = dhan.available_cash()
    except Exception:
        cash = None
    try:
        pos = dhan.positions_grid()
        n_pos = int(pos.get("row_count") or 0)
    except Exception:
        n_pos = 0
    snapshot = {
        "cycles": RUNNER.cycles_completed,
        "last_cycle_at": RUNNER.last_cycle_at,
        "token_ok": _token_ok(),
        "strategy_mode": RUNNER.mode,
        "kill_switch": RUNNER.kill.active,
        "deployed_notional": 0,
        "open_positions_tracked": n_pos,
        "available_cash": cash,
        "capital_tier": "standard",
        "capital_source": "broker",
        "shadow_book_halted": bool(shadow.get("halted")),
        "circuit_breaker_tripped": bool(circuit.get("tripped")),
        "circuit_breaker_soft_halt": bool(circuit.get("soft_halt")),
        "portfolio_unrealized_pnl": None,
        "mtm_stale": False,
        "nifty_spot": spots.get("nifty_spot"),
        "banknifty_spot": spots.get("banknifty_spot"),
        "underlying_spots": {
            "NIFTY": spots.get("NIFTY"),
            "BANKNIFTY": spots.get("BANKNIFTY"),
        },
        "audit_log": {"writes": len(RUNNER.audit), "failures": 0},
        "observability": {
            "audit_dir": str(get_settings().audit_dir),
            "structured_log_dir": str(get_settings().audit_dir),
        },
    }
    return {
        "bridge": {
            "runner_state": RUNNER.state,
            "runner_started_at": RUNNER.started_at,
            "snapshot_at": _now(),
            "last_error": RUNNER.last_error,
            "runner_mode": RUNNER.mode,
        },
        "snapshot": snapshot,
        "nifty_spot": spots.get("nifty_spot"),
        "banknifty_spot": spots.get("banknifty_spot"),
        "last_cycle": {"cycle_number": RUNNER.cycles_completed, "success": True},
    }


# ---------- routes ----------

@app.get("/api/v1/desk/status")
def desk_status(_: None = Depends(require_api_key)):
    """MVP home snapshot. UI must use this instead of /health/full."""
    if _mock_on():
        return ok(MOCK.exclusive_sync(desk_status_payload))
    return ok(desk_status_payload())


@app.get("/api/v1/desk/research/stable")
def research_stable_catalog(_: None = Depends(require_api_key)):
    """Client-locked packs; most_stable = lowest peak DD per underlying."""
    s = get_settings()
    return ok(
        research_stable.stable_catalog(
            nifty_root=s.nifty_lab_root,
            bn_root=s.bn_lab_root,
        )
    )


@app.get("/api/v1/desk/research/stable/{underlying}")
def research_stable_book(underlying: str, _: None = Depends(require_api_key)):
    """Most stable locked pack for NIFTY or BANKNIFTY (+ UI summary/chart)."""
    s = get_settings()
    try:
        payload = research_stable.stable_for_underlying(
            nifty_root=s.nifty_lab_root,
            bn_root=s.bn_lab_root,
            underlying=underlying,
        )
    except KeyError as exc:
        return ok({"error": str(exc), "underlying": underlying})
    return ok(payload)


@app.get("/api/v1/desk/health/full")
def health_full(_: None = Depends(require_api_key)):
    return ok(health_full_payload())


@app.get("/api/v1/desk/runner")
def runner_get(_: None = Depends(require_api_key)):
    return ok(RUNNER.status())


class StartRunnerBody(BaseModel):
    mode: str = "paper"
    execution: Optional[str] = None
    speed: Optional[float] = None
    strategy: str = "edge_fade"
    max_cycles: Optional[int] = None
    operator_id: str = "ops"
    confirm_live: bool = False


class StopRunnerBody(BaseModel):
    operator_id: str = "ops"
    reason: str = "stop"
    timeout_seconds: int = 30


@app.post("/api/v1/desk/runner/start")
def runner_start(body: StartRunnerBody, _: None = Depends(require_api_key)):
    """Arm trading only — does NOT start/stop the VPS desk process."""
    mode = (body.mode or "paper").lower()
    if mode not in ("paper", "mock", "live"):
        mode = "paper"
    execution = (body.execution or "manual").lower()
    if execution not in ("manual", "auto"):
        execution = "manual"
    if RUNNER.kill.active:
        return ok(
            {
                "accepted": False,
                "code": "KILL_SWITCH",
                "command": "start",
                "runner_state": RUNNER.state,
                "trading_active": False,
                "desk_process": "alive",
                "message": "Kill switch is on. Trading was not started.",
            }
        )
    if mode in ("paper", "live"):
        shadow = books.shadow_book_status(_books())
        halted = list(shadow.get("halted_underlyings") or [])
        if set(halted) >= {"NIFTY", "BANKNIFTY"}:
            return ok(
                {
                    "accepted": False,
                    "code": "SHADOW_HALTED",
                    "command": "start",
                    "runner_state": RUNNER.state,
                    "trading_active": False,
                    "desk_process": "alive",
                    "message": "Both books are halted. Trading was not started.",
                }
            )
    already = RUNNER.trading_active() and RUNNER.mode == mode
    RUNNER.state = "RUNNING"
    RUNNER.mode = mode
    RUNNER.task_id = uuid4().hex[:12] if not already else RUNNER.task_id
    RUNNER.started_at = RUNNER.started_at or _now()
    RUNNER.stop_requested = False
    RUNNER.last_error = None
    replay = None
    if mode == "mock":
        speed = float(body.speed or 60)
        replay = MOCK.exclusive_sync(lambda: MOCK.start(execution=execution, speed=speed))
        RUNNER.execution = execution
        RUNNER.replay_day = replay.get("day")
        RUNNER.speed = speed
        already = False
    else:
        MOCK.exclusive_sync(MOCK.discard)
        RUNNER.execution = execution
        RUNNER.replay_day = None
        from app import auto_engine

        if not already:
            auto_engine.load_persisted()
        if mode == "paper" and execution == "auto":
            RUNNER.paper_auto_schedule = True
            RUNNER.paused_day = None
        elif mode != "paper":
            RUNNER.paper_auto_schedule = False
    RUNNER.persist()
    RUNNER.audit_event("trading.start", mode=mode, operator_id=body.operator_id, execution=RUNNER.execution)
    if mode == "mock":
        msg = f"mock replay armed ({RUNNER.execution}, {int(RUNNER.speed)}x)"
    elif already:
        msg = "server was already running"
    else:
        msg = f"trading armed in {mode} ({RUNNER.execution})"
    data = {
        "accepted": True,
        "code": "OK",
        "command": "start",
        "runner_state": RUNNER.state,
        "trading_active": True,
        "desk_process": "alive",
        "mode": mode,
        "execution": RUNNER.execution,
        "message": msg,
    }
    if mode == "mock":
        data["replay"] = MOCK.exclusive_sync(MOCK.replay)
    return ok(data)


@app.post("/api/v1/desk/runner/stop")
def runner_stop(body: StopRunnerBody, _: None = Depends(require_api_key)):
    """Disarm trading only — VPS uvicorn / desk API keeps running."""
    RUNNER.stop_requested = True
    RUNNER.state = "STOPPED"
    if (RUNNER.mode or "").lower() == "mock":
        MOCK.exclusive_sync(MOCK.stop)
    if (RUNNER.mode or "").lower() == "paper":
        from app.schedule import pause_today

        pause_today()
    RUNNER.persist()
    RUNNER.audit_event("trading.stop", operator_id=body.operator_id, reason=body.reason)
    return ok(
        {
            "accepted": True,
            "code": "OK",
            "command": "stop",
            "runner_state": RUNNER.state,
            "trading_active": False,
            "desk_process": "alive",
            "message": "trading stopped (desk API + token renew stay online)",
        }
    )


@app.get("/api/v1/desk/positions")
def positions(_: None = Depends(require_api_key)):
    if _mock_on():
        return ok(MOCK.exclusive_sync(MOCK.ledger.positions_grid))
    try:
        return ok(dhan.positions_grid())
    except Exception as exc:  # noqa: BLE001
        return ok({"rows": [], "row_count": 0, "snapshot_at": _now(), "detail": str(exc)})


@app.get("/api/v1/desk/orders/open")
def orders_open(_: None = Depends(require_api_key)):
    if _mock_on():
        return ok(MOCK.exclusive_sync(MOCK.ledger.open_orders))
    try:
        return ok(dhan.open_orders_response())
    except Exception as exc:  # noqa: BLE001
        return ok({"orders": [], "count": 0, "snapshot_at": _now(), "detail": str(exc)})


@app.get("/api/v1/desk/trades/today")
def trades_today(_: None = Depends(require_api_key)):
    """Today's closed/open rounds from shadow journals (not live positions)."""
    if _mock_on():
        return ok(MOCK.exclusive_sync(MOCK.ledger.trades_today))
    return ok(books.trades_today(_books()))


@app.get("/api/v1/desk/signals/today")
def signals_today(_: None = Depends(require_api_key)):
    """Today's engine Trade Cards for Gate 5 shadow vs fills."""
    if _mock_on():
        return ok(MOCK.exclusive_sync(MOCK.ledger.signals_today))
    return ok(books.signals_today(_books()))


@app.get("/api/v1/desk/contracts")
def contracts(
    underlying: str = Query(..., description="NIFTY or BANKNIFTY"),
    expiry: Optional[str] = Query(None),
    _: None = Depends(require_api_key),
):
    und = underlying.upper()
    if _mock_on():
        return ok(MOCK.exclusive_sync(lambda: MOCK.contracts(und)))
    if und not in ("NIFTY", "BANKNIFTY"):
        return ok(
            {
                "underlying": und,
                "spot": None,
                "lot_size": default_lot_size("NIFTY"),
                "expiry": None,
                "expiries": [],
                "atm_strike": None,
                "strike_step": 50,
                "strikes": [],
            }
        )
    spots = _spots_safe()
    spot = spots.get("nifty_spot") if und == "NIFTY" else spots.get("banknifty_spot")
    return ok(
        chain_snapshot(
            underlying=und,
            expiry=expiry,
            spot=spot,
            session_day=session_day(),
        )
    )


@app.get("/api/v1/desk/quotes/option")
def quotes_option(
    security_id: Optional[str] = Query(None),
    underlying: Optional[str] = Query(None),
    expiry: Optional[str] = Query(None),
    strike: Optional[float] = Query(None),
    option_type: Optional[str] = Query(None),
    _: None = Depends(require_api_key),
):
    if _mock_on():
        return ok(
            MOCK.exclusive_sync(
                lambda: MOCK.quote_option(
                    security_id=security_id,
                    underlying=underlying,
                    expiry=expiry,
                    strike=strike,
                    option_type=option_type,
                )
            )
        )
    try:
        if security_id:
            contract = resolve_contract(underlying=(underlying or "NIFTY").upper(), security_id=security_id)
        else:
            if not (underlying and expiry and strike is not None and option_type):
                return ok(
                    {
                        "underlying": underlying,
                        "expiry": expiry,
                        "strike": strike,
                        "option_type": option_type,
                        "security_id": None,
                        "tradingsymbol": None,
                        "lot_size": None,
                        "ltp": None,
                        "bid": None,
                        "ask": None,
                        "quoted_at": _now(),
                        "stale": True,
                    }
                )
            contract = resolve_contract(
                underlying=underlying.upper(),
                expiry=expiry,
                strike=strike,
                option_type=option_type,
                session_day=session_day(),
            )
        q = dhan.market_quote_option(contract.security_id)
        ltp = q.get("ltp")
        bid = q.get("bid") if q.get("bid") is not None else ltp
        ask = q.get("ask") if q.get("ask") is not None else ltp
        return ok(
            {
                "underlying": contract.underlying,
                "expiry": contract.expiry,
                "strike": contract.strike,
                "option_type": contract.option_type,
                "security_id": contract.security_id,
                "tradingsymbol": contract.tradingsymbol,
                "lot_size": contract.lot_size,
                "ltp": ltp,
                "bid": bid,
                "ask": ask,
                "quoted_at": q.get("quoted_at") or _now(),
                "stale": bool(q.get("stale")),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return ok(
            {
                "underlying": (underlying or "").upper() if underlying else None,
                "expiry": expiry,
                "strike": strike,
                "option_type": option_type,
                "security_id": security_id,
                "tradingsymbol": None,
                "lot_size": None,
                "ltp": None,
                "bid": None,
                "ask": None,
                "quoted_at": _now(),
                "stale": True,
                "detail": str(exc)[:240],
            }
        )


@app.get("/api/v1/desk/quotes/spot")
def quotes_spot(_: None = Depends(require_api_key)):
    if _mock_on():
        return ok(MOCK.exclusive_sync(MOCK.spots))
    try:
        pack = dhan.spots_with_change()
    except Exception:
        pack = {"NIFTY": {"ltp": None, "change_pct": None}, "BANKNIFTY": {"ltp": None, "change_pct": None}}
    return ok(pack)


@app.get("/api/v1/desk/gates")
def gates(
    underlying: str = Query(...),
    sleeve: Optional[str] = Query(None),
    _: None = Depends(require_api_key),
):
    und = underlying.upper()
    if _mock_on():
        payload = MOCK.exclusive_sync(lambda: MOCK.gates(und))
        if sleeve:
            sl = sleeve.lower()
            payload["sleeves"] = [s for s in payload["sleeves"] if s["sleeve"] == sl] or payload["sleeves"]
        return ok(payload)
    book = books.book_by_underlying(_books(), und)
    lot = default_lot_size(und) if und in ("NIFTY", "BANKNIFTY") else 1
    if book is None:
        return ok(
            {
                "trading_active": RUNNER.trading_active(),
                "market_session": market_session(),
                "underlying": und,
                "lot_size": lot,
                "sleeves": [],
            }
        )
    sleeves = books.sleeve_gates(book)
    if sleeve:
        sl = sleeve.lower()
        sleeves = [s for s in sleeves if s["sleeve"] == sl] or sleeves
    return ok(
        {
            "trading_active": RUNNER.trading_active(),
            "market_session": market_session(),
            "underlying": und,
            "lot_size": lot,
            "sleeves": sleeves,
        }
    )


@app.get("/api/v1/desk/triggers/active")
def triggers_active(_: None = Depends(require_api_key)):
    if _mock_on():
        return ok(MOCK.exclusive_sync(_active_trigger))
    return ok(_active_trigger())


class TriggerAckBody(BaseModel):
    trigger_id: str
    action: str = "dismiss"


@app.post("/api/v1/desk/triggers/ack")
def triggers_ack(body: TriggerAckBody, _: None = Depends(require_api_key)):
    action = body.action if body.action in ("dismiss", "opened_ticket") else "dismiss"
    return ok(trigger_store.ack(body.trigger_id, action))


@app.post("/api/v1/desk/sync")
def desk_sync(_: None = Depends(require_api_key)):
    """Drop stale view and rebuild positions/orders/cash from Dhan + shadow state."""
    if _mock_on():
        def _mock_sync():
            pos = MOCK.ledger.positions_grid()
            oo = MOCK.ledger.open_orders()
            RUNNER.last_sync_at = _now()
            RUNNER.persist()
            return pos, oo

        pos, oo = MOCK.exclusive_sync(_mock_sync)
        return ok(
            {
                "accepted": True,
                "code": "OK",
                "message": "Mock ledger rebuilt from sim time (no broker).",
                "last_sync_at": RUNNER.last_sync_at,
                "sync_stats": {
                    "positions_updated": int(pos.get("row_count") or 0),
                    "orders_updated": int(oo.get("count") or 0),
                    "cash_updated": True,
                    "shadow_rebuilt": ["NIFTY", "BANKNIFTY"],
                    "shadow_errors": [],
                },
            }
        )
    detail: Optional[str] = None
    positions_n = 0
    orders_n = 0
    cash_ok = False
    try:
        pos = dhan.positions_grid()
        positions_n = int(pos.get("row_count") or 0)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
    try:
        oo = dhan.open_orders_response()
        orders_n = int(oo.get("count") or 0)
    except Exception as exc:  # noqa: BLE001
        detail = (detail + "; " if detail else "") + str(exc)
    try:
        cash_ok = dhan.available_cash() is not None
    except Exception as exc:  # noqa: BLE001
        detail = (detail + "; " if detail else "") + str(exc)
    rebuilt = books.rebuild_books_from_shadow(_books())
    accepted = detail is None
    RUNNER.last_sync_at = _now()
    RUNNER.persist()
    RUNNER.audit_event(
        "desk.sync",
        positions=positions_n,
        orders=orders_n,
        cash_ok=cash_ok,
        rebuilt=rebuilt.get("rebuilt"),
    )
    if accepted:
        return ok(
            {
                "accepted": True,
                "code": "OK",
                "message": "Desk state synchronized with broker.",
                "last_sync_at": RUNNER.last_sync_at,
                "sync_stats": {
                    "positions_updated": positions_n,
                    "orders_updated": orders_n,
                    "cash_updated": cash_ok,
                    "shadow_rebuilt": rebuilt.get("rebuilt") or [],
                    "shadow_errors": rebuilt.get("errors") or [],
                },
            }
        )
    return ok(
        {
            "accepted": False,
            "code": "SYNC_FAILED",
            "message": f"Broker positions did not refresh. {detail}"[:240],
            "last_sync_at": RUNNER.last_sync_at,
            "sync_stats": {
                "positions_updated": positions_n,
                "orders_updated": orders_n,
                "cash_updated": cash_ok,
                "shadow_rebuilt": rebuilt.get("rebuilt") or [],
                "shadow_errors": rebuilt.get("errors") or [],
            },
        }
    )


@app.get("/api/v1/desk/orders/queue")
def orders_queue(_: None = Depends(require_api_key)):
    return ok(
        {
            "depth": len(RUNNER.order_queue),
            "stats": {"queued": len(RUNNER.order_queue)},
            "snapshot_at": _now(),
            "items": list(RUNNER.order_queue[-50:]),
        }
    )


@app.get("/api/v1/desk/signals/last-cycle")
def signals_last(_: None = Depends(require_api_key)):
    data = books.last_cycle_signals(_books())
    RUNNER.signals_collected = int(data["funnel"]["collected"])
    RUNNER.signals_approved = int(data["funnel"]["approved"])
    RUNNER.signals_rejected = int(data["funnel"]["collected"]) - int(data["funnel"]["approved"])
    return ok(data)


@app.get("/api/v1/desk/signals/rejected")
def signals_rejected(_: None = Depends(require_api_key)):
    return ok(books.rejected_only(_books()))


@app.get("/api/v1/desk/safety/kill-switch")
def kill_get(_: None = Depends(require_api_key)):
    k = RUNNER.kill
    return ok(
        {
            "mode": "kill",
            "active": k.active,
            "activated_at": k.activated_at,
            "operator_id": k.operator_id,
            "reason": k.reason,
        }
    )


class KillBody(BaseModel):
    operator_id: str = "ops"
    reason: str = "manual"
    active: Optional[bool] = None


@app.post("/api/v1/desk/safety/kill-switch")
def kill_set(body: KillBody, _: None = Depends(require_api_key)):
    active = True if body.active is None else bool(body.active)
    RUNNER.kill.active = active
    RUNNER.kill.operator_id = body.operator_id
    RUNNER.kill.reason = body.reason
    RUNNER.kill.activated_at = _now() if active else None
    if active:
        RUNNER.state = "STOPPED"
        RUNNER.stop_requested = True
    RUNNER.persist()
    RUNNER.audit_event("kill_switch", active=active, operator_id=body.operator_id, reason=body.reason)
    return ok(
        {
            "command": "kill-switch",
            "runner_state": RUNNER.state,
            "desk_process": "alive",
            "message": f"kill_switch active={active} (desk API stays up)",
        }
    )


@app.get("/api/v1/desk/safety/circuit-breaker")
def circuit_get(_: None = Depends(require_api_key)):
    return ok(books.circuit_from_books(_books()))


@app.get("/api/v1/desk/safety/shadow-book")
def shadow_get(_: None = Depends(require_api_key)):
    return ok(books.shadow_book_status(_books()))


@app.get("/api/v1/desk/system/token")
def token_get(_: None = Depends(require_api_key)):
    return ok(dhan.token_status())


class TokenBody(BaseModel):
    access_token: Optional[str] = None
    client_id: Optional[str] = None
    pin: Optional[str] = None
    totp_secret: Optional[str] = None
    generate_now: bool = False


@app.post("/api/v1/desk/system/token")
def token_set(body: TokenBody, _: None = Depends(require_api_key)):
    import os

    updates: Dict[str, str] = {}
    if body.client_id:
        os.environ["DHAN_CLIENT_ID"] = body.client_id.strip()
        updates["DHAN_CLIENT_ID"] = body.client_id.strip()
    if body.pin:
        os.environ["DHAN_PIN"] = body.pin.strip()
        updates["DHAN_PIN"] = body.pin.strip()
    if body.totp_secret:
        os.environ["DHAN_TOTP_SECRET"] = body.totp_secret.strip().replace(" ", "")
        updates["DHAN_TOTP_SECRET"] = os.environ["DHAN_TOTP_SECRET"]
    if updates:
        dhan.persist_env_vars(updates)

    if body.access_token:
        dhan.set_access_token(body.access_token.strip(), body.client_id, persist=True)

    auto: Dict[str, Any]
    try:
        if body.generate_now and os.environ.get("DHAN_TOTP_SECRET") and os.environ.get("DHAN_PIN"):
            auto = dhan.generate_access_token_totp(persist=True)
        else:
            auto = dhan.ensure_fresh_token()
    except Exception as exc:  # noqa: BLE001
        auto = {"ok": False, "action": "error", "detail": str(exc)}

    st = dhan.token_status()
    bits = []
    if body.access_token:
        bits.append("access token")
    if body.pin or body.totp_secret:
        bits.append("TOTP credentials")
    what = " + ".join(bits) or "settings"
    return ok(
        {
            **st,
            "auto": auto,
            "message": f"Saved {what} to desk .env on this host; auto-renew/TOTP will keep tokens fresh",
        }
    )


@app.post("/api/v1/desk/system/token/renew")
def token_renew(_: None = Depends(require_api_key)):
    try:
        result = dhan.ensure_fresh_token(renew_if_within_sec=23 * 3600)
        st = dhan.token_status()
        RUNNER.audit_event("token.renew_manual", **{k: v for k, v in result.items() if k != "raw_keys"})
        return ok({**st, "auto": result, "message": result.get("action")})
    except Exception as exc:  # noqa: BLE001
        return ok({"token_ok": False, "message": str(exc), **dhan.token_status()})


@app.get("/api/v1/desk/audit/tail")
def audit_tail(limit: int = 100, _: None = Depends(require_api_key)):
    events = RUNNER.audit[-max(1, min(limit, 500)) :]
    return ok({"count": len(events), "events": events})


# ---------- paper OMS ----------

class PaperOrderBody(BaseModel):
    underlying: str = Field(..., description="NIFTY or BANKNIFTY")
    sleeve: str = "fade"
    security_id: Optional[str] = None
    side: str = "BUY"
    quantity: Optional[int] = None
    lots: int = Field(..., ge=1)
    symbol: str = ""
    strike: float
    option_type: str
    expiry: str
    day: Optional[str] = None
    tag: str = "paper"
    dry_run: bool
    expected_ltp: Optional[float] = None
    price_tolerance: Optional[float] = 0.5
    operator_id: str = "ui"
    trace_id: Optional[str] = None


@app.post("/api/v1/desk/orders/paper")
def paper_order(body: PaperOrderBody, _: None = Depends(require_api_key)):
    """UI-only paper place. Engine must not call this. TRADEABLE cards never auto-place."""
    if (RUNNER.mode or "").lower() == "mock":
        return ok(MOCK.exclusive_sync(lambda: place_paper(body, _books())))
    return ok(place_paper(body, _books()))


class CancelBody(BaseModel):
    order_id: str
    operator_id: str = "ui"


@app.post("/api/v1/desk/orders/cancel")
def cancel_order(body: CancelBody, _: None = Depends(require_api_key)):
    if (RUNNER.mode or "").lower() == "mock":
        return ok(MOCK.exclusive_sync(lambda: cancel_paper(body.order_id, body.operator_id)))
    return ok(cancel_paper(body.order_id, body.operator_id))


@app.post("/api/v1/desk/cycle/tick")
def cycle_tick(_: None = Depends(require_api_key)):
    """Manual cycle bump — only when trading is armed."""
    def _payload():
        return health_tick_payload()

    if not RUNNER.trading_active():
        data = MOCK.exclusive_sync(_payload) if _mock_on() else _payload()
        return ok({**data, "message": "trading stopped — cycle not advanced"})
    RUNNER.bump_cycle()
    data = MOCK.exclusive_sync(_payload) if _mock_on() else _payload()
    return ok(data)


@app.websocket("/ws/desk")
async def ws_desk(websocket: WebSocket):
    if not await require_ws_api_key(websocket):
        return
    await websocket.accept()
    await websocket.send_json(
        {
            "type": "connected",
            "server_time": _now(),
            "channels": ["health.tick", "signal.trigger", "signal.clear"],
        }
    )
    last_tid: Optional[str] = None
    try:
        while True:
            if _mock_on():
                health = await MOCK.exclusive(health_tick_payload)
            else:
                health = health_tick_payload()
            trig = health.get("trigger") or {"active": False, "trigger": None}
            await websocket.send_json(
                {
                    "type": "health.tick",
                    "server_time": _now(),
                    "data": health,
                }
            )
            tid = (trig.get("trigger") or {}).get("trigger_id") if trig.get("active") else None
            if tid and tid != last_tid:
                await websocket.send_json(
                    {"type": "signal.trigger", "server_time": _now(), "data": trig["trigger"]}
                )
            if last_tid and not tid:
                await websocket.send_json(
                    {"type": "signal.clear", "server_time": _now(), "data": {"trigger_id": last_tid}}
                )
            last_tid = tid
            await asyncio.sleep(1.0 if _mock_on() else 5.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "service": "options-edge-desk",
        "desk_process": "alive",
        "trading_active": RUNNER.trading_active(),
        "runner_state": RUNNER.state,
    }
