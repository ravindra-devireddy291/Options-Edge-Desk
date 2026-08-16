#!/usr/bin/env python3
"""Probe VPS and start edge-desk under chroot without host systemd."""
from __future__ import annotations

import os
import sys

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")
CHROOT = "/mnt/sys"
REMOTE = "/root/Options-Edge-Desk"
PY = "/root/Options-Edge-Lab/.venv/bin/python3"
DESK_KEY = os.environ.get("DESK_API_KEY", "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c=")


def run(c, cmd: str, timeout: int = 120) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    print(f"[{code}] {cmd}\n{out}\n---", flush=True)
    return out


def main() -> int:
    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    run(c, "findmnt /mnt/sys || (mkdir -p /mnt/sys && mount /dev/vdb1 /mnt/sys)")
    run(c, f"ls {CHROOT}{REMOTE} | head")
    run(c, "ps -p 1 -o comm=")

    # Patch .env paths + DESK_API_KEY + Dhan from BN lab (idempotent)
    patch = f"""
from pathlib import Path
desk = Path('{REMOTE}/.env')
bn = Path('/root/Options-Edge-Lab/.env')
vals = {{}}
if desk.exists():
    for line in desk.read_text().splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k,v = line.split('=',1)
            vals[k.strip()] = v.strip()
vals.update({{
  'DESK_API_KEY': {DESK_KEY!r},
  'DESK_MODE': 'paper',
  'NIFTY_LAB_ROOT': '/root/Options-Nifty-Edge-Lab',
  'BN_LAB_ROOT': '/root/Options-Edge-Lab',
  'NIFTY_CONFIG': 'config/rungs/paper_2l_nifty_tier2_recommended.yaml',
  'BN_CONFIG': 'config/edge_book_2l_dd20.yaml',
  'LIVE_NIFTY': '0',
  'LIVE_BANKNIFTY': '0',
}})
if bn.exists():
    for line in bn.read_text().splitlines():
        if line.startswith('DHAN_CLIENT_ID=') or line.startswith('DHAN_ACCESS_TOKEN='):
            k,v = line.split('=',1)
            vals[k] = v.strip()
desk.parent.mkdir(parents=True, exist_ok=True)
desk.write_text('\\n'.join(f'{{k}}={{v}}' for k,v in vals.items()) + '\\n')
print('patched', sorted(vals))
"""
    sftp = c.open_sftp()
    helper = f"{CHROOT}{REMOTE}/scripts/_patch_env.py"
    run(c, f"mkdir -p {CHROOT}{REMOTE}/scripts", timeout=30)
    with sftp.file(helper, "w") as fh:
        fh.write(patch)
    sftp.close()
    run(c, f"chroot {CHROOT} bash -lc '{PY} {REMOTE}/scripts/_patch_env.py'")
    run(
        c,
        f"chroot {CHROOT} bash -lc 'grep -E \"^(DESK_API_KEY|NIFTY_LAB|BN_LAB|LIVE_|DHAN_CLIENT)\" {REMOTE}/.env | sed \"s/=.*/=***/\"'",
    )

    # Kill prior desk uvicorn if any, then start under nohup (host has no systemd)
    run(
        c,
        f"chroot {CHROOT} bash -lc '"
        f"pkill -f \"uvicorn app.main:app\" || true; "
        f"mkdir -p {REMOTE}/data/audit {REMOTE}/logs; "
        f"cd {REMOTE}; "
        f"set -a; . {REMOTE}/.env; set +a; "
        f"export PYTHONPATH={REMOTE}; "
        f"nohup {PY} -m uvicorn app.main:app --host 127.0.0.1 --port 8080 "
        f"> {REMOTE}/logs/desk.out 2>&1 & echo started_pid=$!; sleep 3; "
        f"curl -s http://127.0.0.1:8080/healthz; echo; "
        f"curl -s -H \"X-API-Key: $DESK_API_KEY\" http://127.0.0.1:8080/api/v1/desk/runner; echo'",
        timeout=180,
    )
    run(c, f"tail -n 40 {CHROOT}{REMOTE}/logs/desk.out 2>/dev/null || true")
    c.close()
    print("desk bring-up done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
