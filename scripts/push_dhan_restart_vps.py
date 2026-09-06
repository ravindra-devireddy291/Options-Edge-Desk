#!/usr/bin/env python3
"""Push Dhan secrets into VPS desk .env and hard-restart uvicorn (mount /proc)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"
KEY = os.environ.get("DESK_API_KEY", "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c=")


def _read_local_dhan() -> tuple[str, str]:
    for p in (
        Path(r"D:\Options-Edge-Lab\.env"),
        Path(r"D:\Options-Nifty-Edge-Lab\.env"),
    ):
        if not p.exists():
            continue
        client = token = ""
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("DHAN_CLIENT_ID="):
                client = line.split("=", 1)[1].strip().strip('"')
            if line.startswith("DHAN_ACCESS_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"')
        if client and token:
            return client, token
    raise SystemExit("local DHAN_* not found in lab .env files")


def run(c, cmd: str, timeout: int = 120) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    print(f"[{code}] {cmd}\n{out}\n---", flush=True)
    return out


def main() -> int:
    client_id, token = _read_local_dhan()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    # mount proc/sys for chroot process mgmt
    run(c, "mountpoint -q /mnt/sys/proc || mount -t proc proc /mnt/sys/proc")
    run(c, "mountpoint -q /mnt/sys/dev || mount --bind /dev /mnt/sys/dev")

    # write secrets via sftp (avoid shell escaping of JWT)
    sftp = c.open_sftp()
    remote_env = f"{CHROOT}{DESK}/.env"
    # read existing
    try:
        with sftp.file(remote_env, "r") as fh:
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    vals: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    vals.update(
        {
            "DESK_API_KEY": KEY,
            "DESK_MODE": "paper",
            "NIFTY_LAB_ROOT": "/root/Options-Nifty-Edge-Lab",
            "BN_LAB_ROOT": "/root/Options-Edge-Lab",
            "NIFTY_CONFIG": "config/rungs/nifty_alpha.yaml",
            "BN_CONFIG": "config/rungs/bn_alpha.yaml",
            "LIVE_NIFTY": "0",
            "LIVE_BANKNIFTY": "0",
            "DHAN_CLIENT_ID": client_id,
            "DHAN_ACCESS_TOKEN": token,
        }
    )
    with sftp.file(remote_env, "w") as fh:
        for k, v in vals.items():
            fh.write(f"{k}={v}\n")
    sftp.close()
    print("wrote remote .env with Dhan + desk key", flush=True)

    # kill listeners on 8080 from host namespace (proc mounted)
    run(c, "fuser -k 8080/tcp 2>/dev/null || true; sleep 1")
    run(
        c,
        f"chroot {CHROOT} bash -lc '"
        f"fuser -k 8080/tcp 2>/dev/null || true; "
        f"pkill -f \"uvicorn app.main:app\" || true; sleep 1; "
        f"cd {DESK}; set -a; . {DESK}/.env; set +a; export PYTHONPATH={DESK}; "
        f"nohup /root/Options-Edge-Lab/.venv/bin/python3 -m uvicorn app.main:app "
        f"--host 127.0.0.1 --port 8080 > {DESK}/logs/desk.out 2>&1 & sleep 3; "
        f"ss -ltnp | grep 8080 || netstat -ltnp 2>/dev/null | grep 8080; "
        f"curl -s http://127.0.0.1:8080/healthz; echo; "
        f"curl -s -H \"X-API-Key: $DESK_API_KEY\" http://127.0.0.1:8080/api/v1/desk/system/token; echo'",
        timeout=180,
    )
    run(c, f"tail -n 25 {CHROOT}{DESK}/logs/desk.out")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
