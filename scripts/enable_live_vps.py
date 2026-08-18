#!/usr/bin/env python3
"""Flip VPS desk from paper-month to live. Same weekday auto path; Dhan live.

Does NOT run unless you pass --confirm-client-ready after written client confirmation.

  set EDGE_VPS_PASS=...
  py -3 scripts/enable_live_vps.py --confirm-client-ready

Sets DESK_LIVE_ENABLED=1, LIVE_NIFTY=1, LIVE_BANKNIFTY=1, restarts edge-desk.
Next weekday ~09:10 IST the schedule arms live+auto (process still boots STOPPED).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"

LIVE_KEYS = {
    "DESK_LIVE_ENABLED": "1",
    "LIVE_NIFTY": "1",
    "LIVE_BANKNIFTY": "1",
}


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Enable live on the VPS desk after client confirmation.")
    parser.add_argument(
        "--confirm-client-ready",
        action="store_true",
        help="Required. Written client confirmation that the paper month is done.",
    )
    args = parser.parse_args()
    if not args.confirm_client_ready:
        print("Refusing: pass --confirm-client-ready after written client confirmation.", file=sys.stderr)
        return 2
    _load_local_env()
    password = os.environ.get("EDGE_VPS_PASS") or PASS
    if not password:
        print("Set EDGE_VPS_PASS", file=sys.stderr)
        return 2

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=password, timeout=60, allow_agent=False, look_for_keys=False)
    remote = f"{CHROOT}{DESK}/.env"
    sftp = c.open_sftp()
    try:
        with sftp.file(remote, "r") as fh:
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        print("VPS desk .env missing", file=sys.stderr)
        sftp.close()
        c.close()
        return 1
    vals: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    vals.update(LIVE_KEYS)
    with sftp.file(remote, "w") as fh:
        for k, v in vals.items():
            fh.write(f"{k}={v}\n")
    sftp.close()
    _, o, e = c.exec_command(
        "systemctl restart edge-desk; sleep 4; systemctl is-active edge-desk; "
        "curl -s --max-time 10 http://127.0.0.1:8080/healthz || true",
        timeout=60,
    )
    print((o.read() + e.read()).decode("utf-8", "replace"), flush=True)
    c.close()
    print("live flags set; desk restarted. Confirm GET /status live_enabled=true before the next cash open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
