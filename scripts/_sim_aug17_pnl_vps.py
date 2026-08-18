"""Replay 2026-08-17 journals + BN fade option path. No orders. No secrets."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"
REMOTE = "/root/Options-Edge-Desk/scripts/_sim_aug17_inner.py"
LOCAL_INNER = Path(__file__).with_name("_sim_aug17_inner.py")


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
    c.connect(
        HOST,
        username="root",
        password=os.environ["EDGE_VPS_PASS"],
        timeout=60,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = c.open_sftp()
    sftp.put(str(LOCAL_INNER), f"{CHROOT}{REMOTE}")
    sftp.close()
    cmd = f"chroot {CHROOT} bash -lc '/root/Options-Edge-Lab/.venv/bin/python3 {REMOTE}'"
    _, o, e = c.exec_command(cmd, timeout=180)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
