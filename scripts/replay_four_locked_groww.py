#!/usr/bin/env python3
"""Replay all four locked packs on data_lake_groww and compare YAML snapshots."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

DESK = Path(__file__).resolve().parents[1]
NIFTY = Path(r"D:\Options-Nifty-Edge-Lab")
BN = Path(r"D:\Options-Edge-Lab")
LAKE = NIFTY / "data_lake_groww"
OUT = DESK / "reports" / "qa" / "harvest" / "replay_four_locked_groww.json"

os.environ["DATA_LAKE_ROOT"] = str(LAKE)
os.environ["EDGE_LAB_ROOT"] = str(NIFTY)
sys.path[:0] = [str(NIFTY), str(BN), str(DESK)]

from edge_lab.backtest.compound_book import compound_book  # noqa: E402
from edge_lab.risk.execution_brakes import (  # noqa: E402
    fade_params_from_config,
    load_book_config,
)

import yaml  # noqa: E402

PACKS = (
    ("nifty_alpha", NIFTY / "config/rungs/nifty_alpha.yaml", date(2021, 7, 1), "nifty"),
    ("nifty_stable", NIFTY / "config/rungs/nifty_stable.yaml", date(2021, 7, 1), "nifty"),
    ("bn_alpha", BN / "config/rungs/bn_alpha.yaml", date(2021, 9, 9), "banknifty"),
    ("bn_stable", BN / "config/rungs/bn_stable.yaml", date(2021, 9, 9), "banknifty"),
)
END = date(2026, 6, 30)
TOL = {"return_pct": 1.0, "peak_dd_pct": 0.5, "n_trades": 2, "net_pnl_inr": 5000}


def _excluded(kind: str) -> list[str]:
    paths = []
    if kind == "nifty":
        paths = [
            NIFTY / "reports/nifty_enrich/g5_qa_post_dhan_fallback.json",
            NIFTY / "reports/nifty_enrich/g5_qa.json",
            DESK / "reports/nifty_enrich/g5_qa_post_dhan_fallback.json",
        ]
    else:
        paths = [
            DESK / "reports/banknifty_enrich/g5_qa_post_dhan_fallback.json",
            DESK / "reports/banknifty_enrich/g5_qa.json",
            NIFTY / "reports/banknifty_enrich/g5_qa_post_dhan_fallback.json",
            NIFTY / "reports/banknifty_enrich/g5_qa.json",
            BN / "reports/banknifty_enrich/g5_qa.json",
        ]
    for p in paths:
        if not p.is_file():
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        days = [
            str(e.get("day") or e.get("date") or "")[:10]
            for e in (raw.get("excluded_sessions") or [])
        ]
        return [d for d in days if d]
    return []


def _run(path: Path, start: date, excluded: list[str]) -> dict:
    cfg = load_book_config(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    fade = fade_params_from_config(cfg)
    result = compound_book(
        LAKE,
        start=start,
        end=END,
        capital=float(cfg.total_capital_inr or 200_000),
        mode=str(raw.get("mode") or "fade_only"),
        sizing_mode="risk_budget",
        target_risk_inr=float(getattr(cfg, "target_risk_inr", 0) or 40_000),
        max_premium_frac=float(cfg.max_premium_frac or 0.30),
        max_premium_inr=0.0,
        max_lots=0,
        fixed_lots_fade=None,
        fixed_lots_orb=None,
        max_dd_pct=float(cfg.max_dd_pct),
        daily_dd_governor=True,
        excluded_sessions=excluded,
        zero_return_penalty=True,
        shadow_while_halted=False,
        fade_overrides=fade,
        month_ce_stop_halt_n=int(cfg.month_ce_stop_halt_n),
        quiet=True,
        include_day_trades=False,
        # Locked Groww Nifty/BN standards discovery used a single 09:30 open
        # (entry_window_minutes=0). Do not pass a 5-minute window here.
        entry_window_minutes=0,
        est_premium_per_lot=float(cfg.est_premium_per_lot or 6_000),
        fade_weight=1.0,
    )
    s = result.get("summary") or {}
    return {
        "return_pct": round(float(s.get("return_pct") or 0), 2),
        "peak_dd_pct": round(float(s.get("max_dd_pct") or 0), 2),
        "net_pnl_inr": round(float(s.get("net_pnl") or 0), 0),
        "n_trades": int(s.get("n_trades") or 0),
    }


def main() -> int:
    if not LAKE.is_dir():
        raise SystemExit(f"missing lake {LAKE}")
    rows = []
    all_ok = True
    for name, path, start, kind in PACKS:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        snap = dict(raw.get("backtest_snapshot") or {})
        ex = _excluded(kind)
        print(f"RUN {name} start={start} excluded={len(ex)} board={raw.get('board_id')}", flush=True)
        t0 = time.time()
        got = _run(path, start, ex)
        elapsed = round(time.time() - t0, 1)
        diffs = {}
        ok = True
        for k, tol in TOL.items():
            if k not in snap:
                continue
            exp = float(snap[k])
            delta = abs(float(got[k]) - exp)
            hit = delta <= tol
            diffs[k] = {"expected": exp, "got": got[k], "delta": round(delta, 4), "ok": hit}
            ok = ok and hit
        all_ok = all_ok and ok
        row = {
            "pack": name,
            "board_id": raw.get("board_id"),
            "excluded": len(ex),
            "elapsed_s": elapsed,
            "got": got,
            "snapshot": {k: snap.get(k) for k in TOL if k in snap},
            "diffs": diffs,
            "match": ok,
        }
        rows.append(row)
        print(
            f" DONE {name} match={ok} ret={got['return_pct']} "
            f"dd={got['peak_dd_pct']} n={got['n_trades']} {elapsed}s",
            flush=True,
        )
    report = {
        "lake": str(LAKE),
        "end": END.isoformat(),
        "all_match": all_ok,
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("WROTE", OUT, "all_match", all_ok, flush=True)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
