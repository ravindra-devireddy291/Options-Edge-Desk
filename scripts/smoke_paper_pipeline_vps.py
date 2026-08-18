"""Run the same ingest+journal the desk keeper uses — now, not at 09:10.

  py -3 scripts/smoke_paper_pipeline_vps.py
  py -3 scripts/smoke_paper_pipeline_vps.py --day 2026-08-17
"""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"

INNER = r"""
import json, os, subprocess, sys
from datetime import date
from pathlib import Path
from collections import Counter

DAY = os.environ.get("SMOKE_DAY") or date.today().isoformat()
desk = Path("/root/Options-Edge-Desk")
for ln in (desk / ".env").read_text().splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

py = "/root/Options-Edge-Lab/.venv/bin/python3"
books = [
    ("NIFTY", Path("/root/Options-Nifty-Edge-Lab"), os.environ.get("NIFTY_CONFIG") or "config/rungs/paper_2l_nifty_tier2_recommended.yaml"),
    ("BANKNIFTY", Path("/root/Options-Edge-Lab"), os.environ.get("BN_CONFIG") or "config/edge_book_2l_dd20.yaml"),
]

def run(lab, cmd, timeout=480):
    print("+", lab.name, " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(lab), capture_output=True, text=True, timeout=timeout, env=dict(os.environ))
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    print(out[-2500:], flush=True)
    print("exit", p.returncode, flush=True)
    return p.returncode, out

results = []
for name, lab, cfg in books:
    print("\n========", name, DAY, "========", flush=True)
    daily = lab / "scripts/run_shadow_daily.py"
    cmd = [py, str(daily), "--day", DAY, "--config", cfg, "--skip-sync"]
    code, out = run(lab, cmd)
    journal = lab / "reports/shadow" / f"shadow_{DAY}.jsonl"
    rows = []
    if journal.exists():
        for ln in journal.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    st = Counter(str((r.get("lab") or {}).get("status") or "?") for r in rows)
    tr = Counter(str(bool(r.get("tradeable"))) for r in rows)
    sleeves = []
    for r in rows:
        labr = r.get("lab") or {}
        sleeves.append({
            "sleeve": r.get("sleeve"),
            "tradeable": r.get("tradeable"),
            "status": labr.get("status"),
            "symbol": labr.get("symbol"),
            "strike": labr.get("strike"),
            "side": labr.get("side"),
            "gate": (r.get("execution") or {}).get("reason"),
        })
    rec = {
        "book": name,
        "exit": code,
        "journal_exists": journal.exists(),
        "bytes": journal.stat().st_size if journal.exists() else 0,
        "rows": len(rows),
        "lab_status": dict(st),
        "tradeable": dict(tr),
        "sleeves": sleeves,
    }
    results.append(rec)
    print("SUMMARY", json.dumps(rec, default=str)[:1200], flush=True)

print("\n======== ROLLUP ========", flush=True)
print(json.dumps(results, default=str, indent=2), flush=True)
ok = all(r["exit"] == 0 and r["journal_exists"] for r in results)
print("PIPELINE_OK" if ok else "PIPELINE_FAIL", flush=True)
sys.exit(0 if ok else 1)
"""


def main() -> int:
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="")
    args = ap.parse_args()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        os.environ.get("EDGE_VPS_HOST", HOST),
        username="root",
        password=os.environ["EDGE_VPS_PASS"],
        timeout=60,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = c.open_sftp()
    helper = f"{CHROOT}/tmp/_smoke_paper_pipeline.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    day_export = f"SMOKE_DAY={args.day} " if args.day else ""
    _, o, e = c.exec_command(
        f"chroot {CHROOT} bash -lc '{day_export}/root/Options-Edge-Lab/.venv/bin/python3 /tmp/_smoke_paper_pipeline.py'",
        timeout=1000,
    )
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
