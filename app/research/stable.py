"""Serve client-locked backtest packs — most stable = lowest peak DD."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SPAN = "2021-07 → 2026-06"
INITIAL_CAPITAL = 200_000.0


@dataclass(frozen=True)
class PackDef:
    pack_id: str
    underlying: str  # NIFTY | BANKNIFTY
    role: str
    config_rel: str
    tape_rel: str
    run_id: Optional[str] = None  # for multi-run JSON
    selection: str = "locked"  # most_stable | alternate | locked


# Client-locked menu. Most stable per book = lowest peak_dd among paper packs.
PACKS: Tuple[PackDef, ...] = (
    PackDef(
        pack_id="nifty_tier1_conservative",
        underlying="NIFTY",
        role="Institutional DD-first (most stable)",
        config_rel="config/rungs/paper_2l_nifty_tier1_conservative.yaml",
        tape_rel="reports/nifty_trades_tier1_conservative_2l.json",
        selection="most_stable",
    ),
    PackDef(
        pack_id="nifty_tier2_recommended",
        underlying="NIFTY",
        role="Yield sweet spot (Gate 5 default)",
        config_rel="config/rungs/paper_2l_nifty_tier2_recommended.yaml",
        tape_rel="reports/nifty_trades_tier2_recommended_2l.json",
        selection="alternate",
    ),
    PackDef(
        pack_id="bn_paper_25pct_2l",
        underlying="BANKNIFTY",
        role="Client paper pack (most stable paper)",
        config_rel="config/edge_book_2l_premium50k_dd20.yaml",
        tape_rel="reports/clean_25pct_gap300_scale.json",
        run_id="clean_25pct_2l",
        selection="most_stable",
    ),
    PackDef(
        pack_id="bn_live_freeze_2l",
        underlying="BANKNIFTY",
        role="Live-freeze honest (lower return, separate mandate)",
        config_rel="config/edge_book_2l_dd20.yaml",
        tape_rel="reports/live_freeze_2l_honest.json",
        selection="alternate",
    ),
)


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pick_run(raw: Dict[str, Any], run_id: Optional[str]) -> Dict[str, Any]:
    if run_id and isinstance(raw.get("runs"), list):
        for run in raw["runs"]:
            if str(run.get("id") or "") == run_id:
                return run
        raise KeyError(f"run_id not found: {run_id}")
    if "investor" in raw or "months" in raw or "summary" in raw:
        return raw
    raise KeyError("unrecognized tape shape")


def _investor_metrics(run: Dict[str, Any]) -> Dict[str, float]:
    inv = run.get("investor") or {}
    summary = run.get("summary") or {}
    return_pct = float(inv.get("return_pct", summary.get("return_pct", 0.0)))
    peak_dd = float(inv.get("peak_dd_pct", summary.get("max_dd_pct", summary.get("peak_dd_pct", 0.0))))
    net_pnl = float(inv.get("net_pnl", summary.get("net_pnl", 0.0)))
    n_trades = int(inv.get("n_trades", summary.get("n_trades", 0)))
    start_eq = float(summary.get("start_equity", INITIAL_CAPITAL))
    end_eq = float(summary.get("end_equity", start_eq + net_pnl))
    avg_lots = inv.get("avg_lots", summary.get("avg_lots"))
    out = {
        "return_pct": return_pct,
        "peak_dd_pct": peak_dd,
        "net_pnl": net_pnl,
        "n_trades": float(n_trades),
        "start_equity": start_eq,
        "end_equity": end_eq,
    }
    if avg_lots is not None:
        try:
            out["avg_lots"] = float(avg_lots)
        except (TypeError, ValueError):
            pass
    return out


def _win_rate(trades: List[Dict[str, Any]]) -> Optional[float]:
    if not trades:
        return None
    wins = 0
    for t in trades:
        if "net_pnl" in t:
            if float(t["net_pnl"]) > 0:
                wins += 1
        elif t.get("is_tp") is True:
            wins += 1
        elif t.get("win") is True:
            wins += 1
    return wins / len(trades)


def _period_from_months(months: List[Dict[str, Any]]) -> Dict[str, str]:
    if not months:
        return {"start": "2021-07-01", "end": "2026-06-30"}
    first = str(months[0].get("ym") or "2021-07")
    last = str(months[-1].get("ym") or "2026-06")
    return {"start": f"{first}-01", "end": f"{last}-28"}


def _equity_points(months: List[Dict[str, Any]], start_equity: float) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    peak = start_equity
    # seed point at start
    points.append(
        {
            "date": "2021-07-01",
            "timestamp": "2021-07-01T15:30:00+05:30",
            "timestamp_ns": 1_625_119_800_000_000_000,
            "total_equity": round(start_equity, 2),
            "drawdown_pct": 0.0,
        }
    )
    for m in months:
        ym = str(m.get("ym") or "")
        if len(ym) < 7:
            continue
        # month-end proxy
        date = f"{ym}-28"
        eq = float(m.get("equity_after") or start_equity)
        peak = max(peak, eq)
        dd = ((eq - peak) / peak) if peak > 0 else 0.0
        # crude ns from YYYY-MM
        y, mo = int(ym[:4]), int(ym[5:7])
        ns = int((__import__("datetime").datetime(y, mo, 28, 15, 30).timestamp()) * 1_000_000_000)
        points.append(
            {
                "date": date,
                "timestamp": f"{date}T15:30:00+05:30",
                "timestamp_ns": ns,
                "total_equity": round(eq, 2),
                "drawdown_pct": round(dd, 6),
            }
        )
    return points


def _ui_summary(
    *,
    strategy: str,
    metrics: Dict[str, float],
    period: Dict[str, str],
    win_rate: Optional[float],
    message: str,
) -> Dict[str, Any]:
    # UI KPIGrid expects fractions for return / DD / win_rate
    return {
        "status": "COMPLETE",
        "phase": 5,
        "engine_version": "locked-tape",
        "strategy": strategy,
        "period": period,
        "initial_capital": metrics["start_equity"],
        "total_return": metrics["return_pct"] / 100.0,
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "max_drawdown": -abs(metrics["peak_dd_pct"]) / 100.0,
        "win_rate": win_rate,
        "profit_factor": None,
        "total_trades": int(metrics["n_trades"]),
        "message": message,
        "analytics_summary": {
            "round_trip_count": int(metrics["n_trades"]),
            "equity_eod_points": None,
        },
        "locked": {
            "return_pct": metrics["return_pct"],
            "peak_dd_pct": metrics["peak_dd_pct"],
            "net_pnl": metrics["net_pnl"],
            "end_equity": metrics["end_equity"],
        },
    }


def load_pack(lab_root: Path, pack: PackDef) -> Dict[str, Any]:
    tape_path = lab_root / pack.tape_rel
    config_path = lab_root / pack.config_rel
    raw = _load_json(tape_path)
    run = _pick_run(raw, pack.run_id)
    metrics = _investor_metrics(run)
    months = list(run.get("months") or [])
    trades = list(run.get("trades") or [])
    period = _period_from_months(months)
    points = _equity_points(months, metrics["start_equity"])
    if points and points[0]["date"] == "2021-07-01" and months:
        # align seed date to first month start
        first_ym = str(months[0].get("ym") or "2021-07")
        points[0]["date"] = f"{first_ym}-01"
        points[0]["timestamp"] = f"{first_ym}-01T09:15:00+05:30"
    wr = _win_rate(trades)
    avg_lots = metrics.get("avg_lots")
    if avg_lots is None and trades:
        lots_vals = []
        for t in trades:
            v = t.get("lots")
            if v is None:
                continue
            try:
                lots_vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if lots_vals:
            avg_lots = sum(lots_vals) / len(lots_vals)
            metrics["avg_lots"] = avg_lots
    summary = _ui_summary(
        strategy=pack.pack_id,
        metrics=metrics,
        period=period,
        win_rate=wr,
        message=f"Locked {pack.role} · {SPAN}",
    )
    if summary["analytics_summary"] is not None:
        summary["analytics_summary"]["equity_eod_points"] = len(points)

    recipe = run.get("recipe") or raw.get("recipe") or {}
    return {
        "pack_id": pack.pack_id,
        "underlying": pack.underlying,
        "role": pack.role,
        "selection": pack.selection,
        "span": SPAN,
        "config_path": str(config_path).replace("\\", "/"),
        "tape_path": str(tape_path).replace("\\", "/"),
        "tape_exists": tape_path.exists(),
        "config_exists": config_path.exists(),
        "recipe": recipe if isinstance(recipe, dict) else {"id": recipe},
        "metrics": {
            "return_pct": metrics["return_pct"],
            "peak_dd_pct": metrics["peak_dd_pct"],
            "net_pnl": metrics["net_pnl"],
            "n_trades": int(metrics["n_trades"]),
            "start_equity": metrics["start_equity"],
            "end_equity": metrics["end_equity"],
            "win_rate": wr,
            "green_months": sum(1 for m in months if str(m.get("color") or "").lower() == "green"),
            "n_months": len(months),
            **({"avg_lots": round(float(metrics["avg_lots"]), 2)} if metrics.get("avg_lots") is not None else {}),
        },
        "summary": summary,
        "chart": {
            "points": points,
            "initial_capital": metrics["start_equity"],
            "count": len(points),
            "eod_only": True,
        },
    }


def stable_catalog(*, nifty_root: Path, bn_root: Path) -> Dict[str, Any]:
    roots = {"NIFTY": nifty_root, "BANKNIFTY": bn_root}
    packs: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for pack in PACKS:
        try:
            packs.append(load_pack(roots[pack.underlying], pack))
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "pack_id": pack.pack_id,
                    "underlying": pack.underlying,
                    "error": str(exc),
                    "tape": pack.tape_rel,
                }
            )

    most_stable: Dict[str, Any] = {}
    for p in packs:
        if p.get("selection") == "most_stable":
            most_stable[p["underlying"]] = p

    # overall: lowest peak DD among most_stable selections
    overall = None
    for p in most_stable.values():
        if overall is None or float(p["metrics"]["peak_dd_pct"]) < float(overall["metrics"]["peak_dd_pct"]):
            overall = p

    return {
        "selection_rule": "lowest_peak_dd among client-locked paper packs (per underlying)",
        "span": SPAN,
        "most_stable": most_stable,
        "overall_most_stable": {
            "underlying": overall["underlying"],
            "pack_id": overall["pack_id"],
            "peak_dd_pct": overall["metrics"]["peak_dd_pct"],
            "return_pct": overall["metrics"]["return_pct"],
        }
        if overall
        else None,
        "packs": packs,
        "errors": errors,
    }


def stable_for_underlying(*, nifty_root: Path, bn_root: Path, underlying: str) -> Dict[str, Any]:
    u = underlying.strip().upper()
    if u in ("BN", "BANK", "BANK_NIFTY"):
        u = "BANKNIFTY"
    catalog = stable_catalog(nifty_root=nifty_root, bn_root=bn_root)
    selected = catalog["most_stable"].get(u)
    if not selected:
        # fall back: first pack for underlying
        for p in catalog["packs"]:
            if p["underlying"] == u:
                selected = p
                break
    if not selected:
        raise KeyError(f"no locked pack for {u}")
    alternates = [p for p in catalog["packs"] if p["underlying"] == u and p["pack_id"] != selected["pack_id"]]
    return {
        "selection_rule": catalog["selection_rule"],
        "underlying": u,
        "selected": selected,
        "alternates": alternates,
        "errors": [e for e in catalog["errors"] if e["underlying"] == u],
    }
