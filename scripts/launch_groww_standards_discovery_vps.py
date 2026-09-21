#!/usr/bin/env python3
"""Launch Groww buy-side STANDARDS discovery on VPS (parallel tmux tracks).

Four concurrent tracks (sell-side excluded):
  gs_geom  — gap × smart_skip frequency ladder
  gs_exit  — TP/stop/CE-halt on mid-frequency gaps
  gs_orb   — ORB-only buying
  gs_base  — alpha/stable/g150/g175 baselines under risk_budget

Jobs split across 10 cores (leave ~2 for desk): 3+3+2+1.

Usage:
  py -3 scripts/launch_groww_standards_discovery_vps.py
  py -3 scripts/launch_groww_standards_discovery_vps.py --status
  py -3 scripts/launch_groww_standards_discovery_vps.py --fetch
  py -3 scripts/launch_groww_standards_discovery_vps.py --merge
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import paramiko


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PORT = int(os.environ.get("EDGE_VPS_PORT", "443"))
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")

NIFTY = "/root/Options-Nifty-Edge-Lab"
PY = f"{NIFTY}/.venv/bin/python3"
LAKE = f"{NIFTY}/data_lake_groww"
DESK = Path(__file__).resolve().parents[1]

TRACKS = [
    ("gs_geom", "geom", 3),
    ("gs_exit", "exit", 3),
    ("gs_orb", "orb", 2),
    ("gs_base", "base", 1),
]

RUNNER = "scripts/run_groww_standards_discovery_vps.py"
UPLOAD = [
    (DESK / "scripts" / "run_groww_standards_discovery_vps.py", f"{NIFTY}/{RUNNER}"),
    (DESK / "scripts" / "launch_groww_standards_discovery_vps.py",
     f"{NIFTY}/scripts/launch_groww_standards_discovery_vps.py"),
]

FETCH = [
    "reports/nifty_enrich/groww_sweep/groww_standards_geom.json",
    "reports/nifty_enrich/groww_sweep/groww_standards_geom.md",
    "reports/nifty_enrich/groww_sweep/groww_standards_exit.json",
    "reports/nifty_enrich/groww_sweep/groww_standards_exit.md",
    "reports/nifty_enrich/groww_sweep/groww_standards_orb.json",
    "reports/nifty_enrich/groww_sweep/groww_standards_orb.md",
    "reports/nifty_enrich/groww_sweep/groww_standards_base.json",
    "reports/nifty_enrich/groww_sweep/groww_standards_base.md",
]


def _connect() -> paramiko.SSHClient:
    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST, port=PORT, username=USER, password=PASS, timeout=90,
        banner_timeout=90, auth_timeout=90, allow_agent=False, look_for_keys=False,
    )
    return c


def _run(c: paramiko.SSHClient, cmd: str, timeout: int = 120) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()


def status(c: paramiko.SSHClient) -> None:
    load_cmd = "cut -d ' ' -f1-3 /proc/loadavg"
    print(f"host {HOST}:{PORT}")
    print(f"tmux:\n{_run(c, 'tmux ls 2>/dev/null || echo NO_TMUX')}")
    print(f"nproc={_run(c, 'nproc')} load={_run(c, load_cmd)}")
    print(f"desk={_run(c, 'systemctl is-active edge-desk')}")
    for sess, track, _jobs in TRACKS:
        done = f"{NIFTY}/reports/experiments/gs_{track}.done"
        prog = f"{NIFTY}/reports/nifty_enrich/groww_sweep/groww_standards_{track}.progress.json"
        log = f"{NIFTY}/reports/experiments/gs_{track}.log"
        print(f"--- {sess} ---")
        print(f"  done={_run(c, f'test -f {done} && cat {done} || echo NO_DONE')}")
        print(f"  prog={_run(c, f'cat {prog} 2>/dev/null || echo none')}")
        print(f"  log_tail:\n{_run(c, f'tail -n 8 {log} 2>/dev/null || echo no_log')}")


def fetch(c: paramiko.SSHClient) -> None:
    local = DESK / "reports" / "nifty_enrich" / "groww_sweep"
    local.mkdir(parents=True, exist_ok=True)
    sftp = c.open_sftp()
    for rel in FETCH:
        name = Path(rel).name
        try:
            sftp.get(f"{NIFTY}/{rel}", str(local / name))
            print("OK", name, flush=True)
        except OSError as exc:
            print("MISS", name, exc, flush=True)
    for sess, track, _ in TRACKS:
        for extra in (
            f"{NIFTY}/reports/experiments/gs_{track}.log",
            f"{NIFTY}/reports/experiments/gs_{track}.done",
            f"{NIFTY}/reports/nifty_enrich/groww_sweep/groww_standards_{track}.progress.json",
        ):
            name = Path(extra).name
            try:
                sftp.get(extra, str(local / name))
                print("OK", name, flush=True)
            except OSError:
                pass
    sftp.close()


def merge_local() -> None:
    """Merge all track JSONs into one standards verdict."""
    sweep = DESK / "reports" / "nifty_enrich" / "groww_sweep"
    rows: List[Dict[str, Any]] = []
    for track in ("geom", "exit", "orb", "base"):
        p = sweep / f"groww_standards_{track}.json"
        if not p.exists():
            print("skip missing", p.name)
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        rows.extend(raw.get("rows") or [])

    def key(r: dict) -> tuple:
        f = r.get("spans", {}).get("full") or {}
        h = r.get("spans", {}).get("holdout_freeze") or {}
        ntr = int(f.get("n_trades") or 0)
        dd = float(f.get("peak_dd_pct") or 99)
        cagr = float(f.get("cagr_pct") or -999)
        hret = float(h.get("return_pct") or -999)
        cal = float(f.get("calmar") or -999)
        return (
            1 if dd <= 25 else 0,
            1 if hret >= 0 else 0,
            1 if cagr > 0 else 0,
            1 if ntr >= 100 else (1 if ntr >= 60 else 0),
            cal,
            ntr,
            cagr,
        )

    ranked = sorted(rows, key=key, reverse=True)
    out_json = sweep / "groww_standards_merged.json"
    out_md = DESK / "reports" / "nifty_enrich" / "GROWW_STANDARDS_VERDICT.md"
    out_json.write_text(json.dumps({"n": len(ranked), "rows": ranked}, indent=2), encoding="utf-8")

    def pick(min_trades: int, exclude_ids: set) -> dict | None:
        for r in ranked:
            if r.get("id") in exclude_ids:
                continue
            f = r.get("spans", {}).get("full") or {}
            h = r.get("spans", {}).get("holdout_freeze") or {}
            if (
                int(f.get("n_trades") or 0) >= min_trades
                and float(f.get("peak_dd_pct") or 99) <= 25
                and float(h.get("return_pct") or -1) >= 0
                and float(f.get("cagr_pct") or -1) > 0
            ):
                return r
        return None

    primary = pick(100, set())
    stable = pick(60, {primary["id"]} if primary else set())
    # fallback: best by calmar with n>=60 even if holdout soft
    if not primary:
        primary = next(
            (
                r for r in ranked
                if int((r.get("spans", {}).get("full") or {}).get("n_trades") or 0) >= 60
                and float((r.get("spans", {}).get("full") or {}).get("cagr_pct") or -1) > 0
                and float((r.get("spans", {}).get("full") or {}).get("peak_dd_pct") or 99) <= 30
            ),
            ranked[0] if ranked else None,
        )

    lines = [
        "# Groww Standards Verdict (buy-side blackbox)",
        "",
        "Sell-side deferred. Capital Rs 200,000. Lake `data_lake_groww`. Sizing r40/p30/d15.",
        f"Merged candidates: **{len(ranked)}** across geom/exit/orb/base.",
        "",
        "## Proposed standards",
        "",
    ]
    for label, r in (("PRIMARY", primary), ("STABLE", stable)):
        if not r:
            lines.append(f"- **{label}:** none cleared gates")
            continue
        f = r["spans"]["full"]
        h = r["spans"].get("holdout_freeze") or {}
        o = r["spans"].get("oos_2024") or {}
        lines.append(
            f"- **{label}:** `{r['id']}` (track={r.get('track')}) — "
            f"{f.get('n_trades')} trades ({f.get('trades_per_year')}/yr), "
            f"CAGR {f.get('cagr_pct')}%, DD {f.get('peak_dd_pct')}%, Calmar {f.get('calmar')}, "
            f"Sharpe {f.get('sharpe')}; holdout {h.get('return_pct')}% / DD {h.get('peak_dd_pct')}%; "
            f"oos2024 {o.get('return_pct')}%"
        )
        fo = r.get("fade_overrides") or {}
        if fo:
            lines.append(f"  - fade: `{json.dumps(fo, sort_keys=True)}`")
        oo = r.get("orb_overrides") or {}
        if oo:
            lines.append(f"  - orb: `{json.dumps(oo, sort_keys=True)}`")
    lines += [
        "",
        "## Top 25 by gates",
        "",
        "| ID | track | trades | t/yr | CAGR% | DD% | Calmar | Hold% | HoldDD | OOS24% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in ranked[:25]:
        f = r.get("spans", {}).get("full") or {}
        h = r.get("spans", {}).get("holdout_freeze") or {}
        o = r.get("spans", {}).get("oos_2024") or {}
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                r.get("id"),
                r.get("track"),
                f.get("n_trades"),
                f.get("trades_per_year"),
                f.get("cagr_pct"),
                f.get("peak_dd_pct"),
                f.get("calmar"),
                h.get("return_pct"),
                h.get("peak_dd_pct"),
                o.get("return_pct"),
            )
        )
    lines += [
        "",
        "## Decision rules",
        "",
        "- PRIMARY needs denser fills than g150/g175 thin winners (target >=100 trades / ~20/yr).",
        "- STABLE is the next viable denser or more conservative twin.",
        "- If no PRIMARY clears >=100 trades with DD/holdout gates, do **not** promote thin Calmar heroes.",
        "",
    ]
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", out_json)
    print("wrote", out_md)
    if primary:
        print("PRIMARY", primary["id"], primary["spans"]["full"])
    if stable:
        print("STABLE", stable["id"], stable["spans"]["full"])


def watch(c: paramiko.SSHClient, poll_s: int = 90, max_min: int = 240) -> int:
    deadline = time.time() + max_min * 60
    while time.time() < deadline:
        status(c)
        dones = []
        for _sess, track, _ in TRACKS:
            d = _run(c, f"test -f {NIFTY}/reports/experiments/gs_{track}.done && cat {NIFTY}/reports/experiments/gs_{track}.done || echo NO")
            dones.append(d)
        if all("exit=" in d for d in dones):
            fetch(c)
            merge_local()
            bad = [d for d in dones if "exit=0" not in d]
            return 0 if not bad else 1
        time.sleep(poll_s)
    print("watch timeout")
    return 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--poll", type=int, default=90)
    ap.add_argument("--limit", type=int, default=0, help="smoke limit per track")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.merge:
        merge_local()
        return 0

    c = _connect()
    if args.status:
        status(c)
        c.close()
        return 0
    if args.fetch:
        fetch(c)
        c.close()
        return 0
    if args.watch:
        rc = watch(c, poll_s=args.poll)
        c.close()
        return rc

    print("lake:", _run(c, f"du -sh {LAKE} | cut -f1"))
    smoke = _run(
        c,
        f"cd {NIFTY} && DATA_LAKE_ROOT={LAKE} {PY} -c "
        "\"from edge_lab.paths import default_lake;from edge_lab.lake import list_partition_months;"
        "print('opt',len(list_partition_months(default_lake(),'options','NIFTY')))\" 2>&1",
        timeout=180,
    )
    print("smoke:", smoke)
    if "opt 61" not in smoke:
        c.close()
        raise SystemExit("Groww lake not readable")

    # ensure g5 qa present for excluded sessions
    _run(c, f"test -f {NIFTY}/reports/nifty_enrich/g5_qa.json && echo G5_OK || echo G5_MISS")

    sftp = c.open_sftp()
    for src, dst in UPLOAD:
        _run(c, f"mkdir -p $(dirname {dst})")
        sftp.put(str(src), dst)
        print("UP", src.name, flush=True)
    sftp.close()
    _run(c, f"sed -i 's/\\r$//' {NIFTY}/{RUNNER}")
    compile_out = _run(
        c,
        f"cd {NIFTY} && {PY} -m py_compile {RUNNER} 2>&1 && echo COMPILE_OK",
        timeout=120,
    )
    print(compile_out)
    if "COMPILE_OK" not in compile_out:
        c.close()
        raise SystemExit("compile failed")

    _run(c, f"mkdir -p {NIFTY}/reports/nifty_enrich/groww_sweep {NIFTY}/reports/experiments")
    limit_arg = f" --limit {args.limit}" if args.limit else ""

    for sess, track, jobs in TRACKS:
        log = f"{NIFTY}/reports/experiments/gs_{track}.log"
        done = f"{NIFTY}/reports/experiments/gs_{track}.done"
        sh = f"{NIFTY}/scripts/_gs_{track}.sh"
        _run(c, f"rm -f {log} {done} {NIFTY}/reports/nifty_enrich/groww_sweep/groww_standards_{track}.*")
        script = f"""#!/bin/bash
set -u
export DATA_LAKE_ROOT={LAKE}
export EDGE_LAB_ROOT={NIFTY}
export PYTHONUNBUFFERED=1
cd {NIFTY}
echo "=== GS_{track} start $(date -Iseconds) jobs={jobs} ===" >> {log}
{PY} -u {RUNNER} --track {track} --jobs {jobs}{limit_arg} >> {log} 2>&1
rc=$?
echo "exit=$rc $(date -Iseconds)" > {done}
echo "=== GS_{track} exit=$rc $(date -Iseconds) ===" >> {log}
"""
        sftp = c.open_sftp()
        with sftp.file(sh, "w") as fh:
            fh.write(script)
        sftp.close()
        _run(c, f"chmod +x {sh} && sed -i 's/\\r$//' {sh}")
        _run(c, f"tmux kill-session -t {sess} 2>/dev/null; true")
        _run(c, f"tmux new-session -d -s {sess} 'bash {sh}'")
        print(f"launched {sess} track={track} jobs={jobs}{limit_arg}", flush=True)

    status(c)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
