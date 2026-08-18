"""Read-only: is Tuesday paper session ready? No orders. No secret prints."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"

INNER = r"""
import json
from pathlib import Path
import urllib.request

env = {}
for ln in Path("/root/Options-Edge-Desk/.env").read_text().splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        env[k.strip()] = v.strip()
key = env.get("DESK_API_KEY", "")
print("ENV", {k: env.get(k) for k in (
    "DESK_LIVE_ENABLED", "DESK_MOCK_LOOP", "LIVE_NIFTY", "LIVE_BANKNIFTY",
    "DESK_PAPER_AUTO", "DESK_MODE", "NIFTY_LAB_ROOT", "BN_LAB_ROOT",
)})
hz = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/healthz"), timeout=10)
print("HEALTHZ", hz.status)
req = urllib.request.Request(
    "http://127.0.0.1:8080/api/v1/desk/status",
    headers={"X-API-Key": key},
)
with urllib.request.urlopen(req, timeout=25) as r:
    st = json.loads(r.read())
d = st.get("data") if isinstance(st.get("data"), dict) else st
print("STATUS", json.dumps({k: d.get(k) for k in (
    "mode", "execution", "trading_active", "runner_state", "market_session",
    "session_day", "token_ok", "broker_reachable", "live_enabled", "paper_auto",
    "kill_switch_active", "open_positions", "lab_journal", "last_error",
)}, default=str))
for p in (
    "/root/Options-Nifty-Edge-Lab/scripts/run_shadow_daily.py",
    "/root/Options-Edge-Lab/scripts/run_shadow_daily.py",
    "/root/Options-Nifty-Edge-Lab/scripts/run_shadow_journal.py",
    "/root/Options-Edge-Lab/scripts/run_shadow_journal.py",
    "/root/Options-Edge-Desk/app/lab_sync.py",
    "/root/Options-Edge-Desk/app/paper_e2e.py",
):
    print("FILE", Path(p).exists(), p.split("/")[-1])
for root in (
    "/root/Options-Nifty-Edge-Lab/reports/shadow",
    "/root/Options-Edge-Lab/reports/shadow",
):
    files = sorted(Path(root).glob("shadow_*.jsonl"))[-4:]
    print("JOURNALS", Path(root).parent.parent.name, [f.name for f in files])
for lake in (
    "/root/Options-Nifty-Edge-Lab/data_lake",
    "/root/Options-Edge-Lab/data_lake",
):
    p = Path(lake)
    print("LAKE", lake.split("/")[2], "exists", p.exists())
ae = Path("/root/Options-Edge-Desk/app/auto_engine.py").read_text(encoding="utf-8")
print("AUTO_EXPIRY_NONE", "expiry=sig.get(\"expiry\") or None" in ae)
print("LAB_KEEPER_SRC", "lab_sync.tick" in Path("/root/Options-Edge-Desk/app/main.py").read_text(encoding="utf-8"))
"""


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    load_env()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=os.environ["EDGE_VPS_PASS"], timeout=60, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    helper = f"{CHROOT}/tmp/_paper_ready.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(f"chroot {CHROOT} python3 /tmp/_paper_ready.py", timeout=45)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-800:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
