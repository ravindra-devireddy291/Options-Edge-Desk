"""Read-only VPS readiness after unify/live-cutover deploy. No secret prints."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"

INNER = r"""
import json
import subprocess
from pathlib import Path
import urllib.request

def get(path, key, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8080" + path,
        data=data,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())

env = {}
for ln in Path("/root/Options-Edge-Desk/.env").read_text().splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        env[k.strip()] = v.strip()
key = env.get("DESK_API_KEY", "")
print("ENV", {k: env.get(k) for k in (
    "DESK_LIVE_ENABLED", "DESK_MOCK_LOOP", "LIVE_NIFTY", "LIVE_BANKNIFTY", "DESK_PAPER_AUTO", "DESK_MODE"
)})
hz = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/healthz"), timeout=10)
print("HEALTHZ", hz.status)
st = get("/api/v1/desk/status", key)
d = st.get("data") if isinstance(st.get("data"), dict) else st
print("STATUS", json.dumps({k: d.get(k) for k in (
    "mode", "execution", "trading_active", "runner_state", "market_session", "token_ok",
    "broker_reachable", "live_enabled", "paper_auto", "kill_switch_active", "open_positions",
    "lab_journal", "paper_saved", "last_error",
)}, default=str))
for p in (
    "/root/Options-Nifty-Edge-Lab/scripts/run_shadow_journal.py",
    "/root/Options-Edge-Lab/scripts/run_shadow_journal.py",
):
    print("SCRIPT", p, Path(p).exists())
for root in ("/root/Options-Nifty-Edge-Lab/reports/shadow", "/root/Options-Edge-Lab/reports/shadow"):
    files = sorted(Path(root).glob("shadow_*.jsonl"))[-3:]
    print("JOURNALS", root, [f.name for f in files])
for lake in ("/root/Options-Nifty-Edge-Lab/data_lake", "/root/Options-Edge-Lab/data_lake"):
    p = Path(lake)
    print("LAKE", lake, "exists", p.exists(), "children", len(list(p.glob("*"))) if p.exists() else 0)
for ingest in (
    "/root/Options-Nifty-Edge-Lab/scripts/ingest_dhan_nifty.py",
    "/root/Options-Edge-Lab/scripts/ingest_dhan_bn.py",
    "/root/Options-Nifty-Edge-Lab/scripts/run_shadow_daily.py",
    "/root/Options-Edge-Lab/scripts/run_shadow_daily.py",
    "/root/Options-Nifty-Edge-Lab/edge_lab/lake.py",
    "/root/Options-Nifty-Edge-Lab/edge_lab/backtest/run_month.py",
):
    print("FILE", ingest, Path(ingest).exists())
py = "/root/Options-Edge-Lab/.venv/bin/python3"
for lab in ("/root/Options-Nifty-Edge-Lab", "/root/Options-Edge-Lab"):
    r = subprocess.run(
        [py, "-c", "import pandas, pyarrow; from edge_lab.paths import default_lake; from edge_lab.lake import read_spot; from edge_lab.backtest.run_month import run_one_month; print('ok', default_lake())"],
        cwd=lab,
        capture_output=True,
        text=True,
        timeout=30,
    )
    print("IMPORT", lab, r.returncode, (r.stdout or r.stderr)[-200:])
"""


def main() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=os.environ["EDGE_VPS_PASS"], timeout=60, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    helper = f"{CHROOT}/tmp/_verify_cutover.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(f"chroot {CHROOT} python3 /tmp/_verify_cutover.py", timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-800:])
    c.close()


if __name__ == "__main__":
    main()
