"""Reconstruct 2026-08-17: can Dhan still serve that day's 1m spot? Then journal."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"
INNER = r"""
import json, os, subprocess, sys
from pathlib import Path

desk = Path("/root/Options-Edge-Desk")
for ln in (desk / ".env").read_text().splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

py = "/root/Options-Edge-Lab/.venv/bin/python3"

# live spots from desk
import urllib.request
key = os.environ.get("DESK_API_KEY", "")
req = urllib.request.Request("http://127.0.0.1:8080/api/v1/desk/status", headers={"X-API-Key": key})
with urllib.request.urlopen(req, timeout=20) as r:
    st = json.loads(r.read())
d = st.get("data") if isinstance(st.get("data"), dict) else st
print("LIVE_SPOTS", json.dumps({k: d.get(k) for k in ("token_ok","broker_reachable","nifty_spot","banknifty_spot","nifty_change_pct","banknifty_change_pct","mode")}, default=str))

print("\n=== INGEST NIFTY 2026-08-17 SPOT-ONLY ===")
p = subprocess.run(
    [py, "scripts/ingest_dhan_nifty.py", "--from", "2026-08-17", "--to", "2026-08-17", "--spot-only",
     "--lake", "/root/Options-Nifty-Edge-Lab/data_lake"],
    cwd="/root/Options-Nifty-Edge-Lab",
    capture_output=True, text=True, timeout=180, env=dict(os.environ),
)
print("exit", p.returncode)
print((p.stdout or "")[-1500:])
if p.stderr:
    print("stderr", p.stderr[-800:])

print("\n=== INGEST BN 2026-08-17 SPOT-ONLY ===")
p2 = subprocess.run(
    [py, "scripts/ingest_dhan_bn.py", "--from", "2026-08-17", "--to", "2026-08-17", "--spot-only",
     "--lake", "/root/Options-Edge-Lab/data_lake"],
    cwd="/root/Options-Edge-Lab",
    capture_output=True, text=True, timeout=180, env=dict(os.environ),
)
print("exit", p2.returncode)
print((p2.stdout or "")[-1500:])
if p2.stderr:
    print("stderr", p2.stderr[-800:])

print("\n=== READ BACK 2026-08-17 BARS ===")
sys.path.insert(0, "/root/Options-Nifty-Edge-Lab")
from datetime import date
from edge_lab.lake import read_spot, session_dates
from pathlib import Path as P
for lake, und in (
    (P("/root/Options-Nifty-Edge-Lab/data_lake"), "NIFTY"),
    (P("/root/Options-Edge-Lab/data_lake"), "BANKNIFTY"),
):
    try:
        df = read_spot(lake, und, date(2026,8,17), date(2026,8,17))
    except Exception as e:
        print(und, "ERROR", e)
        continue
    days = session_dates(df)
    n = 0 if df is None or df.empty else len(df)
    print(und, "bars", n, "days", [str(x) for x in days])
    if n:
        print("  first", str(df["_ts_ist"].iloc[0]), "last", str(df["_ts_ist"].iloc[-1]), "close_last", float(df["close"].iloc[-1]) if "close" in df.columns else None)
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
    helper = f"{CHROOT}/tmp/_forensic_ingest.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(
        f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 /tmp/_forensic_ingest.py",
        timeout=400,
    )
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-1500:])
    c.close()

if __name__ == "__main__":
    main()
