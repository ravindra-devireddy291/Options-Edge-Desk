"""Backfill prior sessions so fade gap/regime is not no_gap_inputs, then re-journal 17 Aug."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"
INNER = r"""
import json, os, subprocess
from collections import Counter
from pathlib import Path

desk = Path("/root/Options-Edge-Desk")
for ln in (desk / ".env").read_text().splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")
py = "/root/Options-Edge-Lab/.venv/bin/python3"

jobs = [
    ("NIFTY", Path("/root/Options-Nifty-Edge-Lab"), "scripts/ingest_dhan_nifty.py", "config/rungs/paper_2l_nifty_tier2_recommended.yaml"),
    ("BANKNIFTY", Path("/root/Options-Edge-Lab"), "scripts/ingest_dhan_bn.py", "config/edge_book_2l_dd20.yaml"),
]
for name, lab, ingest, cfg in jobs:
    print("==== BACKFILL SPOT", name, "2026-08-03..16 ====", flush=True)
    p = subprocess.run(
        [py, ingest, "--from", "2026-08-03", "--to", "2026-08-16", "--spot-only"],
        cwd=str(lab), capture_output=True, text=True, timeout=180, env=dict(os.environ),
    )
    print((p.stdout or "")[-800:], flush=True)
    if p.stderr:
        print("stderr", p.stderr[-400:], flush=True)
    print("exit", p.returncode, flush=True)
    print("==== REJOURNAL", name, "2026-08-17 ====", flush=True)
    p2 = subprocess.run(
        [py, "scripts/run_shadow_journal.py", "--day", "2026-08-17", "--config", cfg, "--replace"],
        cwd=str(lab), capture_output=True, text=True, timeout=180, env=dict(os.environ),
    )
    print((p2.stdout or "")[-1200:], flush=True)
    j = lab / "reports/shadow/shadow_2026-08-17.jsonl"
    rows = [json.loads(x) for x in j.read_text().splitlines() if x.strip()] if j.exists() else []
    st = Counter(str((r.get("lab") or {}).get("status")) for r in rows)
    print("journal", dict(st), "tradeable", sum(1 for r in rows if r.get("tradeable")), flush=True)
"""

def main() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=os.environ["EDGE_VPS_PASS"], timeout=60, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    helper = f"{CHROOT}/tmp/_backfill_gap.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 /tmp/_backfill_gap.py", timeout=500)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-1000:])
    c.close()

if __name__ == "__main__":
    main()
