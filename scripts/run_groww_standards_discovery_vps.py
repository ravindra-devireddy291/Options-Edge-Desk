#!/usr/bin/env python3
"""Groww buy-side STANDARDS discovery (blackbox) — find Primary + Stable.

Sell-side is OUT OF SCOPE. Goal: two client-grade option-buying standards on
data_lake_groww, ranked for BOTH robustness AND trade frequency (the g150/g175
thin-sample problem).

Tracks (run in parallel tmux sessions via launch_groww_standards_discovery_vps.py):

  geom  — min_gap × smart_skip ladder (incl. dense 60/80/100)
  exit  — TP / stop / CE-halt on mid-frequency gaps
  orb   — ORB-only buying alternatives
  base  — Groww-native alpha/stable baselines under risk_budget sizing

Client gates (applied at ranking time):
  * full DD <= 25%
  * full CAGR > 0 and holdout return >= 0
  * Primary pool: n_trades >= 100 (~20/yr) preferred; Soft floor 60
  * Prefer Calmar, then trades, then lower DD

Pinned sizing (Phase C/E proven): risk 40k, premium 30%, DD cap 15%, daily governor.

Usage:
  DATA_LAKE_ROOT=... py -3 -u scripts/run_groww_standards_discovery_vps.py --track geom --jobs 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
LAB = Path(os.environ.get("EDGE_LAB_ROOT") or ROOT)
if not (LAB / "edge_lab").exists():
    LAB = Path(r"D:\Options-Nifty-Edge-Lab")
for _p in (str(LAB), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CAPITAL = 200_000.0
PIN_RISK = 40_000.0
PIN_FRAC = 0.30
PIN_DD = 0.15

SPANS: Dict[str, Tuple[date, date]] = {
    "full": (date(2021, 7, 1), date(2026, 6, 30)),
    "oos_2021_h2": (date(2021, 7, 1), date(2021, 12, 31)),
    "oos_2024": (date(2024, 1, 1), date(2024, 12, 31)),
    "holdout_freeze": (date(2025, 1, 1), date(2026, 6, 30)),
    "march_2026": (date(2026, 3, 1), date(2026, 3, 31)),
}

OUT = ROOT / "reports" / "nifty_enrich" / "groww_sweep"


def _load_excluded() -> List[str]:
    qa = ROOT / "reports" / "nifty_enrich" / "g5_qa.json"
    if not qa.exists():
        qa = Path(f"{os.environ.get('EDGE_LAB_ROOT', '')}/reports/nifty_enrich/g5_qa.json")
    if not qa.exists():
        return []
    try:
        raw = json.loads(qa.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = [
        str(e.get("day") or e.get("date") or "")[:10]
        for e in (raw.get("excluded_sessions") or [])
    ]
    return [d for d in out if d]


def _grid_geom() -> List[dict]:
    """Frequency ladder — the main answer to 'only 57 trades'."""
    min_gaps = (60.0, 80.0, 100.0, 125.0, 150.0, 175.0, 200.0)
    skips = (150.0, 200.0, 250.0, 300.0)
    out: List[dict] = []
    for mg in min_gaps:
        for sg in skips:
            if sg < mg:
                continue
            vid = "G_g%d_s%d" % (int(mg), int(sg))
            out.append(
                {
                    "id": vid,
                    "track": "geom",
                    "mode": "fade_only",
                    "month_ce_stop_halt_n": 2,
                    "fade_overrides": {
                        "min_gap_pts": mg,
                        "smart_skip_gap_pts": sg,
                        "smart_skip_near_extreme_frac": 0.25,
                        "skip_ce_fade_min_gap_pts": 300.0,
                        "stop_pct": 0.30,
                        "take_profit_pct": 0.50,
                        "regime_mode": "chop_only",
                        "strike_step": 50,
                    },
                }
            )
    return out


def _grid_exit() -> List[dict]:
    """Exit / brake surface on mid-frequency gaps (where paper cycle is viable)."""
    min_gaps = (80.0, 100.0, 125.0, 150.0)
    tps = (0.40, 0.50, 0.60)
    stops = (0.25, 0.30)
    halts = (0, 2)
    out: List[dict] = []
    for mg in min_gaps:
        for tp in tps:
            for st in stops:
                for hn in halts:
                    vid = "E_g%d_tp%d_st%d_h%d" % (
                        int(mg), int(round(tp * 100)), int(round(st * 100)), hn
                    )
                    out.append(
                        {
                            "id": vid,
                            "track": "exit",
                            "mode": "fade_only",
                            "month_ce_stop_halt_n": hn,
                            "fade_overrides": {
                                "min_gap_pts": mg,
                                "smart_skip_gap_pts": max(200.0, mg),
                                "smart_skip_near_extreme_frac": 0.25,
                                "skip_ce_fade_min_gap_pts": 300.0,
                                "stop_pct": st,
                                "take_profit_pct": tp,
                                "regime_mode": "chop_only",
                                "strike_step": 50,
                            },
                        }
                    )
    return out


def _grid_orb() -> List[dict]:
    """ORB-only buying — denser day participation hypothesis."""
    ranges = (30.0, 50.0, 75.0, 100.0)
    tps = (0.50, 0.60, 0.80)
    stops = (0.25, 0.30)
    out: List[dict] = []
    for mr in ranges:
        for tp in tps:
            for st in stops:
                vid = "O_r%d_tp%d_st%d" % (int(mr), int(round(tp * 100)), int(round(st * 100)))
                out.append(
                    {
                        "id": vid,
                        "track": "orb",
                        "mode": "orb_only",
                        "month_ce_stop_halt_n": 0,
                        "fade_overrides": {},
                        "orb_overrides": {
                            "min_range_pts": mr,
                            "stop_pct": st,
                            "take_profit_pct": tp,
                            "strike_step": 50,
                            "entry": "09:50",
                            "exit": "15:20",
                        },
                    }
                )
    return out


def _grid_base() -> List[dict]:
    """Honest Groww baselines under risk_budget (replaces fixed_lots 10 leverage)."""
    return [
        {
            "id": "B_alpha80",
            "track": "base",
            "mode": "fade_only",
            "month_ce_stop_halt_n": 2,
            "fade_overrides": {
                "min_gap_pts": 80.0,
                "smart_skip_gap_pts": 200.0,
                "smart_skip_near_extreme_frac": 0.25,
                "skip_ce_fade_min_gap_pts": 300.0,
                "stop_pct": 0.30,
                "take_profit_pct": 0.50,
                "regime_mode": "chop_only",
                "strike_step": 50,
            },
        },
        {
            "id": "B_stable80",
            "track": "base",
            "mode": "fade_only",
            "month_ce_stop_halt_n": 2,
            "fade_overrides": {
                "min_gap_pts": 80.0,
                "smart_skip_gap_pts": 250.0,
                "smart_skip_near_extreme_frac": 0.25,
                "skip_ce_fade_min_gap_pts": 350.0,
                "stop_pct": 0.30,
                "take_profit_pct": 0.40,
                "regime_mode": "chop_only",
                "strike_step": 50,
            },
        },
        {
            "id": "B_g150",
            "track": "base",
            "mode": "fade_only",
            "month_ce_stop_halt_n": 2,
            "fade_overrides": {
                "min_gap_pts": 150.0,
                "smart_skip_gap_pts": 200.0,
                "smart_skip_near_extreme_frac": 0.25,
                "skip_ce_fade_min_gap_pts": 300.0,
                "stop_pct": 0.30,
                "take_profit_pct": 0.50,
                "regime_mode": "chop_only",
                "strike_step": 50,
            },
        },
        {
            "id": "B_g175",
            "track": "base",
            "mode": "fade_only",
            "month_ce_stop_halt_n": 2,
            "fade_overrides": {
                "min_gap_pts": 175.0,
                "smart_skip_gap_pts": 200.0,
                "smart_skip_near_extreme_frac": 0.25,
                "skip_ce_fade_min_gap_pts": 300.0,
                "stop_pct": 0.30,
                "take_profit_pct": 0.50,
                "regime_mode": "chop_only",
                "strike_step": 50,
            },
        },
    ]


def _grid(track: str) -> List[dict]:
    if track == "geom":
        return _grid_geom()
    if track == "exit":
        return _grid_exit()
    if track == "orb":
        return _grid_orb()
    if track == "base":
        return _grid_base()
    if track == "all":
        return _grid_geom() + _grid_exit() + _grid_orb() + _grid_base()
    raise SystemExit("unknown track %s" % track)


def _run_book(v: dict, d0: date, d1: date, excluded: List[str]) -> dict:
    from edge_lab.backtest.compound_book import compound_book
    from edge_lab.paths import default_lake

    kwargs: Dict[str, Any] = dict(
        capital=CAPITAL,
        mode=str(v.get("mode") or "fade_only"),
        max_dd_pct=PIN_DD,
        max_premium_inr=0.0,
        fade_weight=1.0,
        sizing_mode="risk_budget",
        target_risk_inr=PIN_RISK,
        max_premium_frac=PIN_FRAC,
        est_premium_per_lot=6_000.0,
        max_lots=0,
        daily_dd_governor=True,
        excluded_sessions=excluded,
        zero_return_penalty=True,
        shadow_while_halted=False,
        fixed_lots_fade=None,
        fixed_lots_orb=None,
        fade_overrides=v.get("fade_overrides") or {},
        month_ce_stop_halt_n=int(v.get("month_ce_stop_halt_n") or 0),
        quiet=True,
        include_day_trades=False,
    )
    if v.get("orb_overrides"):
        kwargs["orb_overrides"] = v["orb_overrides"]
    return compound_book(default_lake(), start=d0, end=d1, **kwargs)


def _cagr(ret_pct: float, d0: date, d1: date) -> float:
    years = max((d1 - d0).days / 365.25, 1e-9)
    growth = 1.0 + ret_pct / 100.0
    if growth <= 0:
        return -100.0
    return round(100.0 * (growth ** (1.0 / years) - 1.0), 2)


def _pack(r: dict, d0: date, d1: date) -> dict:
    s = r.get("summary") or {}
    b = r.get("brake_stats") or {}
    months = list(r.get("months") or [])
    ret = float(s.get("return_pct") or 0.0)
    dd = float(s.get("max_dd_pct") or 0.0)
    pnls = [float(m.get("net_pnl") or 0.0) for m in months]
    wins = sum(1 for p in pnls if p > 0)
    ntr = int(s.get("n_trades") or 0)
    years = max((d1 - d0).days / 365.25, 1e-9)
    return {
        "return_pct": round(ret, 2),
        "cagr_pct": _cagr(ret, d0, d1),
        "peak_dd_pct": round(dd, 2),
        "calmar": round((ret / 100.0) / max(dd / 100.0, 1e-6), 3) if dd > 0 else 0.0,
        "net_pnl_inr": round(float(s.get("net_pnl") or 0.0), 2),
        "n_trades": ntr,
        "trades_per_year": round(ntr / years, 2),
        "avg_trade_lots": float(s.get("avg_trade_lots") or 0.0),
        "halt_months": int(s.get("halted_months") or 0),
        "monthly_win_rate": round(wins / len(pnls), 4) if pnls else 0.0,
        "ann_vol_pct": float(s.get("ann_vol_pct") or 0.0),
        "sharpe": float(s.get("sharpe") or 0.0),
        "daily_dd_halts": int(b.get("daily_dd_halts") or 0),
        "daily_dd_halt_days": int(b.get("daily_dd_halt_days") or 0),
        "max_intra_month_dd_pct": float(b.get("max_intra_month_dd_pct") or 0.0),
    }


def _run_one(v: dict, excluded: List[str]) -> dict:
    row: Dict[str, Any] = {
        "id": v["id"],
        "track": v.get("track"),
        "mode": v.get("mode"),
        "fade_overrides": v.get("fade_overrides") or {},
        "orb_overrides": v.get("orb_overrides") or {},
        "month_ce_stop_halt_n": v.get("month_ce_stop_halt_n"),
        "spans": {},
    }
    for name, (d0, d1) in SPANS.items():
        try:
            row["spans"][name] = _pack(_run_book(v, d0, d1, excluded), d0, d1)
        except Exception as exc:  # noqa: BLE001
            print("  ERROR %s %s: %s" % (v["id"], name, exc), flush=True)
            print(traceback.format_exc()[-800:], flush=True)
            row["spans"][name] = {
                "error": "%s: %s" % (type(exc).__name__, exc),
                "return_pct": 0.0, "cagr_pct": 0.0, "peak_dd_pct": 0.0,
                "calmar": 0.0, "n_trades": 0, "trades_per_year": 0.0,
            }
    return row


def _rank_key(r: dict) -> tuple:
    f = r["spans"].get("full") or {}
    h = r["spans"].get("holdout_freeze") or {}
    ntr = int(f.get("n_trades") or 0)
    dd = float(f.get("peak_dd_pct") or 99.0)
    cagr = float(f.get("cagr_pct") or -999.0)
    hret = float(h.get("return_pct") or -999.0)
    cal = float(f.get("calmar") or -999.0)
    # gates encoded as sort keys
    freq_ok = 1 if ntr >= 100 else (1 if ntr >= 60 else 0)
    dd_ok = 1 if dd <= 25.0 else 0
    hold_ok = 1 if hret >= 0.0 else 0
    pos = 1 if cagr > 0 else 0
    return (dd_ok, hold_ok, pos, freq_ok, cal, ntr, cagr)


def _write(track: str, rows: List[dict], total: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ranked = sorted(rows, key=_rank_key, reverse=True)
    out_json = OUT / ("groww_standards_%s.json" % track)
    out_md = OUT / ("groww_standards_%s.md" % track)
    out_json.write_text(
        json.dumps({"track": track, "total": total, "capital": CAPITAL, "rows": ranked}, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Groww standards discovery — track `%s`" % track,
        "",
        "Buy-side only. Sizing pinned r40/p30/d15. Rank: DD<=25, holdout>=0, CAGR>0, then freq>=100, Calmar, trades.",
        "",
        "| ID | trades | t/yr | CAGR% | DD% | Calmar | Sharpe | Holdout% | HoldDD% | OOS24% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in ranked[:50]:
        f = r["spans"].get("full") or {}
        h = r["spans"].get("holdout_freeze") or {}
        o = r["spans"].get("oos_2024") or {}
        lines.append(
            "| `%s` | %d | %.1f | %.2f | %.2f | %.3f | %.3f | %.2f | %.2f | %.2f |"
            % (
                r["id"],
                int(f.get("n_trades") or 0),
                float(f.get("trades_per_year") or 0.0),
                float(f.get("cagr_pct") or 0.0),
                float(f.get("peak_dd_pct") or 0.0),
                float(f.get("calmar") or 0.0),
                float(f.get("sharpe") or 0.0),
                float(h.get("return_pct") or 0.0),
                float(h.get("peak_dd_pct") or 0.0),
                float(o.get("return_pct") or 0.0),
            )
        )
    # candidate callouts
    primary = next(
        (
            r for r in ranked
            if int((r["spans"].get("full") or {}).get("n_trades") or 0) >= 100
            and float((r["spans"].get("full") or {}).get("peak_dd_pct") or 99) <= 25
            and float((r["spans"].get("holdout_freeze") or {}).get("return_pct") or -1) >= 0
            and float((r["spans"].get("full") or {}).get("cagr_pct") or -1) > 0
        ),
        None,
    )
    stable = next(
        (
            r for r in ranked
            if r is not primary
            and int((r["spans"].get("full") or {}).get("n_trades") or 0) >= 60
            and float((r["spans"].get("full") or {}).get("peak_dd_pct") or 99) <= 25
            and float((r["spans"].get("holdout_freeze") or {}).get("return_pct") or -1) >= 0
            and float((r["spans"].get("full") or {}).get("cagr_pct") or -1) > 0
        ),
        None,
    )
    lines += ["", "## Track candidates", ""]
    if primary:
        pf = primary["spans"]["full"]
        lines.append(
            "- **Primary-shaped:** `%s` — %d trades (%.1f/yr), CAGR %.2f%%, DD %.2f%%, Calmar %.3f"
            % (primary["id"], pf["n_trades"], pf["trades_per_year"], pf["cagr_pct"], pf["peak_dd_pct"], pf["calmar"])
        )
    else:
        lines.append("- **Primary-shaped:** none cleared n_trades>=100 + DD/holdout gates")
    if stable:
        sf = stable["spans"]["full"]
        lines.append(
            "- **Stable-shaped:** `%s` — %d trades (%.1f/yr), CAGR %.2f%%, DD %.2f%%, Calmar %.3f"
            % (stable["id"], sf["n_trades"], sf["trades_per_year"], sf["cagr_pct"], sf["peak_dd_pct"], sf["calmar"])
        )
    else:
        lines.append("- **Stable-shaped:** none cleared n_trades>=60 + DD/holdout gates")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote %s" % out_json, flush=True)
    print("wrote %s" % out_md, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True, choices=["geom", "exit", "orb", "base", "all"])
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    grid = _grid(args.track)
    if args.limit:
        grid = grid[: args.limit]
    excluded = _load_excluded()
    print(
        "standards_discovery track=%s cells=%d jobs=%d lake=%s excluded=%d"
        % (args.track, len(grid), args.jobs, os.environ.get("DATA_LAKE_ROOT", "?"), len(excluded)),
        flush=True,
    )
    prog = OUT / ("groww_standards_%s.progress.json" % args.track)
    OUT.mkdir(parents=True, exist_ok=True)
    rows: List[dict] = []
    done = 0
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = {ex.submit(_run_one, v, excluded): v["id"] for v in grid}
        for fut in as_completed(futs):
            r = fut.result()
            rows.append(r)
            done += 1
            prog.write_text(
                json.dumps({"track": args.track, "done": done, "total": len(grid), "last": r.get("id")}, indent=2),
                encoding="utf-8",
            )
            f = (r.get("spans") or {}).get("full") or {}
            print(
                "  OK %s full: CAGR %s DD %s Cal %s n=%s t/yr=%s"
                % (
                    r.get("id"),
                    f.get("cagr_pct"),
                    f.get("peak_dd_pct"),
                    f.get("calmar"),
                    f.get("n_trades"),
                    f.get("trades_per_year"),
                ),
                flush=True,
            )
    _write(args.track, rows, len(grid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
