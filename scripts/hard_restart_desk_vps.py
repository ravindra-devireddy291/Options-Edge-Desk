#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

def _require_desk_api_key() -> str:
    key = (os.environ.get("DESK_API_KEY") or "").strip()
    if not key:
        from pathlib import Path
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("DESK_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        raise SystemExit("Set DESK_API_KEY")
    return key

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vps_desk_restart import CHROOT, DESK, restart_desk  # noqa: E402

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]
KEY = _require_desk_api_key()


def run(cmd: str, timeout: int = 120) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    print(out, flush=True)
    return out


c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

sftp = c.open_sftp()
sftp.put(str(Path(__file__).resolve().parent / "boot_desk.py"), f"{CHROOT}{DESK}/scripts/boot_desk.py")
sftp.close()

restart_desk(run, KEY)
run(f"tail -n 40 {CHROOT}{DESK}/logs/desk.out")
c.close()
