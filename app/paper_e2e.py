"""Lake → journal → compass → OMS dry-run. Never sends a live order.

Used by scripts/e2e_paper_lake_vps.py so we can shake paper gaps without
waiting for the next 09:10 IST cash open.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from app.auth import get_settings
from app.books import adapters as books
from app.oms import place_paper
from app.runners.state import RUNNER
from app.session import session_day


def _books():
    return books.desk_books()


def lake_probe(day: str) -> Dict[str, Any]:
    """Spot/option parquet presence for the IST day (no Dhan calls)."""
    from datetime import date as _date
    import sys

    s = get_settings()
    for root in (s.nifty_lab_root, s.bn_lab_root):
        p = str(root)
        if p not in sys.path:
            sys.path.insert(0, p)
    from edge_lab.lake import read_options, read_spot, session_dates

    out: Dict[str, Any] = {"day": day}
    d = _date.fromisoformat(day)
    for name, root, und in (
        ("NIFTY", s.nifty_lab_root, "NIFTY"),
        ("BANKNIFTY", s.bn_lab_root, "BANKNIFTY"),
    ):
        lake = Path(root) / "data_lake"
        rec: Dict[str, Any] = {"lake": str(lake), "exists": lake.exists()}
        try:
            spot = read_spot(lake, und, d, d)
            opt = read_options(lake, und, d, d)
            rec["spot_bars"] = 0 if spot is None or spot.empty else int(len(spot))
            rec["option_rows"] = 0 if opt is None or opt.empty else int(len(opt))
            rec["spot_sessions"] = [str(x) for x in session_dates(spot)]
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"[:240]
        out[name] = rec
    return out


def compass(day: str) -> Dict[str, Any]:
    raw = books.signals_today(_books(), day)
    signals = list(raw.get("signals") or [])
    by = {"PENDING": [], "SKIPPED": [], "REJECTED": [], "EXECUTED": [], "OTHER": []}
    for s in signals:
        st = str(s.get("status") or "OTHER").upper()
        by.setdefault(st, [])
        if st not in by:
            by["OTHER"].append(s)
        else:
            by[st].append(s)
    return {
        "day": day,
        "count": len(signals),
        "pending": len(by.get("PENDING") or []),
        "skipped": len(by.get("SKIPPED") or []),
        "rejected": len(by.get("REJECTED") or []),
        "executed": len(by.get("EXECUTED") or []),
        "signals": signals,
    }


def dry_run_signal(sig: Dict[str, Any], day: str) -> Dict[str, Any]:
    """OMS preview for one compass card. Does not call Dhan /orders."""
    body = SimpleNamespace(
        underlying=str(sig.get("underlying") or "").upper(),
        sleeve=str(sig.get("sleeve") or "fade").lower(),
        security_id=sig.get("security_id") or None,
        side=str(sig.get("action") or "BUY").upper(),
        quantity=None,
        lots=max(1, int(sig.get("target_lots") or sig.get("lots") or 1)),
        symbol=str(sig.get("symbol") or ""),
        strike=sig.get("target_strike") if sig.get("target_strike") is not None else sig.get("strike"),
        option_type=sig.get("option_type") or "PE",
        expiry=sig.get("expiry") or None,
        day=day,
        tag="edge-desk-e2e",
        dry_run=True,
        expected_ltp=sig.get("ltp"),
        price_tolerance=50.0,
        operator_id="e2e",
        trace_id=None,
        force_session_close=False,
    )
    prev = RUNNER.mode
    RUNNER.mode = "paper"
    try:
        return place_paper(body, _books())
    finally:
        RUNNER.mode = prev


def run(day: str | None = None) -> Dict[str, Any]:
    """Full lake integration. Safe after hours: dry_run only."""
    day = day or session_day().isoformat()
    probe = lake_probe(day)
    comp = compass(day)
    places: List[Dict[str, Any]] = []
    prev = RUNNER.mode
    RUNNER.mode = "paper"
    try:
        for sig in [s for s in comp["signals"] if str(s.get("status") or "").upper() == "PENDING"]:
            placed = dry_run_signal(sig, day)
            places.append(
                {
                    "signal_id": sig.get("signal_id"),
                    "underlying": sig.get("underlying"),
                    "sleeve": sig.get("sleeve"),
                    "accepted": placed.get("accepted"),
                    "code": placed.get("code"),
                    "message": placed.get("message"),
                    "contract": (placed.get("contract") or {}).get("tradingsymbol")
                    if isinstance(placed.get("contract"), dict)
                    else None,
                    "ltp": ((placed.get("quote") or {}).get("ltp") if isinstance(placed.get("quote"), dict) else None),
                }
            )
    finally:
        RUNNER.mode = prev

    gaps: List[str] = []
    for name in ("NIFTY", "BANKNIFTY"):
        rec = probe.get(name) or {}
        if int(rec.get("spot_bars") or 0) < 300:
            gaps.append(f"{name} lake spot bars too low ({rec.get('spot_bars')})")
        if int(rec.get("option_rows") or 0) < 1:
            gaps.append(f"{name} lake has no option rows for {day}")
    if comp["count"] < 1:
        gaps.append("compass empty — journal missing or unread")
    if comp["pending"] == 0 and comp["skipped"] == 0 and comp["rejected"] == 0:
        gaps.append("journal produced no skip/pending/reject cards")
    for p in places:
        if not p.get("accepted"):
            gaps.append(f"dry_run {p.get('signal_id')} {p.get('code')} {p.get('message')}")

    return {
        "day": day,
        "session_day_now": session_day().isoformat(),
        "lake": probe,
        "compass": {
            "count": comp["count"],
            "pending": comp["pending"],
            "skipped": comp["skipped"],
            "rejected": comp["rejected"],
            "executed": comp["executed"],
            "cards": [
                {
                    k: s.get(k)
                    for k in (
                        "signal_id",
                        "underlying",
                        "sleeve",
                        "status",
                        "notes",
                        "symbol",
                        "option_type",
                        "target_strike",
                        "target_lots",
                        "expiry",
                    )
                }
                for s in comp["signals"]
            ],
        },
        "dry_runs": places,
        "gaps": gaps,
        "ok": not gaps,
    }


def main() -> int:
    import sys

    day = sys.argv[1] if len(sys.argv) > 1 else None
    payload = run(day)
    print(json.dumps(payload, default=str, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
