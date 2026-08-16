#!/usr/bin/env python3
"""Finish VPS desk wiring: Dhan secrets, nifty hygiene sync, nginx hint, smoke."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"
NIFTY = "/root/Options-Nifty-Edge-Lab"
BN = "/root/Options-Edge-Lab"
KEY = os.environ.get("DESK_API_KEY", "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c=")


def run(c, cmd: str, timeout: int = 120) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    print(f"[{code}] {cmd}\n{out}\n---", flush=True)
    return out


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    # locate BN .env for Dhan
    run(c, f"ls {CHROOT}{BN}/.env {CHROOT}{NIFTY}/.env 2>&1 | head")
    run(
        c,
        f"chroot {CHROOT} bash -lc \""
        f"python3 - <<'PY'\n"
        f"from pathlib import Path\n"
        f"desk=Path('{DESK}/.env')\n"
        f"vals={{}}\n"
        f"for line in desk.read_text().splitlines():\n"
        f"  if '=' in line and not line.strip().startswith('#'):\n"
        f"    k,v=line.split('=',1); vals[k.strip()]=v.strip()\n"
        f"for p in [Path('{BN}/.env'), Path('{NIFTY}/.env')]:\n"
        f"  if not p.exists():\n"
        f"    continue\n"
        f"  for line in p.read_text().splitlines():\n"
        f"    if line.startswith('DHAN_CLIENT_ID=') or line.startswith('DHAN_ACCESS_TOKEN='):\n"
        f"      k,v=line.split('=',1); vals[k]=v.strip()\n"
        f"vals['DESK_API_KEY']={KEY!r}\n"
        f"desk.write_text('\\n'.join(f'{{k}}={{v}}' for k,v in vals.items())+'\\n')\n"
        f"print('has_dhan_client', bool(vals.get('DHAN_CLIENT_ID')))\n"
        f"print('has_dhan_token', bool(vals.get('DHAN_ACCESS_TOKEN')))\n"
        f"print('keys', sorted(k for k in vals if not k.startswith('DHAN_ACCESS')))\n"
        f"PY\"",
    )

    # upload nifty hygiene scripts if missing
    local_nifty = Path(r"D:\Options-Nifty-Edge-Lab")
    sftp = c.open_sftp()
    for rel in (
        "scripts/sync_shadow_fills_from_dhan.py",
        "scripts/run_shadow_daily.py",
    ):
        lp = local_nifty / rel
        if not lp.exists():
            print("skip missing", rel, flush=True)
            continue
        remote = f"{CHROOT}{NIFTY}/{rel}"
        run(c, f"mkdir -p $(dirname {remote})", timeout=30)
        sftp.put(str(lp), remote)
        print("scp", rel, flush=True)
    # nginx sample into place (manual enable)
    sftp.put(
        str(Path(r"D:\Options-Edge-Desk\deploy\nginx-desk.conf")),
        f"{CHROOT}{DESK}/deploy/nginx-desk.conf",
    )
    sftp.close()

    # restart desk to pick up Dhan env
    run(
        c,
        f"chroot {CHROOT} bash -lc '"
        f"pkill -f \"uvicorn app.main:app\" || true; sleep 1; "
        f"cd {DESK}; set -a; . {DESK}/.env; set +a; export PYTHONPATH={DESK}; "
        f"nohup /root/Options-Edge-Lab/.venv/bin/python3 -m uvicorn app.main:app "
        f"--host 127.0.0.1 --port 8080 > {DESK}/logs/desk.out 2>&1 & sleep 3; "
        f"curl -s http://127.0.0.1:8080/healthz; echo; "
        f"curl -s -H \"X-API-Key: $DESK_API_KEY\" http://127.0.0.1:8080/api/v1/desk/system/token; echo; "
        f"curl -s -H \"X-API-Key: $DESK_API_KEY\" http://127.0.0.1:8080/api/v1/desk/signals/last-cycle | head -c 400; echo'",
        timeout=180,
    )
    run(c, f"tail -n 20 {CHROOT}{DESK}/logs/desk.out")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
