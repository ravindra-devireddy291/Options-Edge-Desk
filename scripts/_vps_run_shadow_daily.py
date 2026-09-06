#!/usr/bin/env python3
"""Phase 0 daily shadow pipeline: ingest → journal → sync fills → trade card → G5.

Usage (after market / EOD):
  python scripts/run_shadow_daily.py --day 2026-08-11
  python scripts/run_shadow_daily.py --day today

Intraday live/shadow (before entries):
  python scripts/check_execution_gate.py --sleeve fade
  python scripts/check_execution_gate.py --sleeve orb
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge_lab.dhan_client import load_dotenv

DEFAULT_CONFIG = "config/rungs/nifty_alpha.yaml"


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def _parse_day(s: str) -> date:
    if s in ("", "today"):
        return date.today()
    return datetime.strptime(s, "%Y-%m-%d").date()


def write_trade_card(day: date, shadow_dir: Path, config_name: str) -> Path:
    path = shadow_dir / f"shadow_{day.isoformat()}.jsonl"
    card = shadow_dir / f"TRADE_CARD_{day.isoformat()}.md"
    state_path = shadow_dir / "execution_state.json"
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))

    equity = state.get("equity")
    peak = state.get("peak_equity") or 0
    dd_pct = (
        round(100.0 * max(0.0, (peak - float(equity)) / peak), 2)
        if peak and equity is not None
        else "—"
    )

    lines = [
        f"# Shadow trade card — {day.isoformat()}",
        "",
        f"Config: `{config_name}` (execution brakes ON).",
        "",
        f"- Equity: ₹{equity if equity is not None else '—'} · DD mode: `{state.get('dd_mode', '—')}` "
        f"· DD%: {dd_pct}",
        f"- Month PnL: ₹{state.get('month_pnl', '—')} · month_halted: {state.get('month_halted')} "
        f"· CE halt: {state.get('month_ce_halt')} · skip_next: {state.get('skip_next_day')}",
        "",
        "**Do not size up.** Only trade sleeves marked TRADEABLE below.",
        "",
        "Pre-entry check: `python scripts/check_execution_gate.py --sleeve fade|orb`",
        "",
    ]
    if not path.exists():
        lines += ["No journal file yet. Run journal step first.", ""]
        card.write_text("\n".join(lines), encoding="utf-8")
        return card

    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    lines.append(
        "| Sleeve | Lab | Tradeable | Gate | Side | Strike | Symbol | Lab entry | Exit | Lab net | Broker? |"
    )
    lines.append(
        "|--------|-----|:---------:|------|------|-------:|--------|----------:|------|---------|:-------:|"
    )
    actionable = []
    for r in rows:
        lab = r.get("lab") or {}
        bf = r.get("broker_fill")
        ex = r.get("execution") or {}
        tradeable = bool(r.get("tradeable"))
        # Legacy rows without tradeable: treat ok as actionable only if no deny
        if "tradeable" not in r:
            tradeable = lab.get("status") == "ok" and ex.get("allow", True) is not False
        lines.append(
            f"| {r.get('sleeve')} | {lab.get('status')} | "
            f"{'YES' if tradeable else 'NO'} | {ex.get('reason') or '-'} | "
            f"{lab.get('side') or '-'} | {lab.get('strike') or '-'} | "
            f"`{lab.get('symbol') or '-'}` | {lab.get('entry') or '-'} | "
            f"{lab.get('exit_reason') or '-'} | {lab.get('net_pnl')} | "
            f"{'Y' if bf else 'N'} |"
        )
        if tradeable:
            actionable.append(r)

    lines += ["", "## How to paper on Dhan", ""]
    if not actionable:
        lines.append(
            "No TRADEABLE sleeves this session — brakes or no signal. "
            "Do **not** place orders. Still counts as a logged session."
        )
    else:
        lines.append(
            "For each TRADEABLE sleeve below, place **config lots** INTRADAY BUY "
            "at ~09:30 (fade) / ~09:50 (ORB) — only if `check_execution_gate` ALLOW:"
        )
        lines.append("")
        for r in actionable:
            lab = r["lab"]
            lots = (r.get("execution") or {}).get("lots") or 1
            lines.append(
                f"1. **{r['sleeve'].upper()}** `{lab.get('symbol')}` "
                f"{lab.get('side')} strike {lab.get('strike')} — "
                f"{lots} lot(s), entry ref {lab.get('entry')}, stop/TP per config."
            )
            lines.append(
                f"   After exit, run: "
                f"`python scripts/record_shadow_fill.py --day {day.isoformat()} "
                f"--sleeve {r['sleeve']} --entry <fill> --exit <fill> --notes paper`"
            )
        lines.append("")
        lines.append("Or place trades in Dhan then: `python scripts/sync_shadow_fills_from_dhan.py --today`")

    lines += [
        "",
        "## G5",
        "",
        "`python scripts/summarize_shadow.py`",
        "",
    ]
    card.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return card


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="today")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--skip-ingest", action="store_true")
    ap.add_argument("--skip-sync", action="store_true")
    ap.add_argument("--py", default=sys.executable)
    args = ap.parse_args()
    day = _parse_day(args.day)
    py = args.py
    shadow = ROOT / "reports" / "shadow"

    if not args.skip_ingest:
        rc = _run(
            [
                py,
                "scripts/ingest_dhan_nifty.py",
                "--from",
                day.isoformat(),
                "--to",
                day.isoformat(),
                "--n-strikes",
                "6",
                "--max-contracts",
                "30",
            ]
        )
        if rc != 0:
            print("WARN ingest failed — continuing with existing lake", flush=True)

    rc = _run(
        [
            py,
            "scripts/run_shadow_journal.py",
            "--day",
            day.isoformat(),
            "--config",
            args.config,
            "--replace",
        ]
    )
    if rc != 0:
        return rc

    if not args.skip_sync:
        _run([py, "scripts/sync_shadow_fills_from_dhan.py", "--today"])
        _run(
            [
                py,
                "scripts/sync_shadow_fills_from_dhan.py",
                "--from",
                day.isoformat(),
                "--to",
                day.isoformat(),
            ]
        )

    _run(
        [
            py,
            "scripts/check_execution_gate.py",
            "--day",
            day.isoformat(),
            "--config",
            args.config,
            "--all",
            "--persist",
        ]
    )

    cfg_name = Path(args.config).stem
    try:
        import yaml

        raw = yaml.safe_load((ROOT / args.config).read_text(encoding="utf-8")) or {}
        cfg_name = str(raw.get("name") or cfg_name)
    except Exception:
        pass

    card = write_trade_card(day, shadow, cfg_name)
    _run([py, "scripts/summarize_shadow.py"])
    print(f"trade_card={card}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
