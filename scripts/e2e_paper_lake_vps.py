"""Run lake→journal→OMS dry-run on the VPS. Never places a live order.

  py -3 scripts/e2e_paper_lake_vps.py
  py -3 scripts/e2e_paper_lake_vps.py --day 2026-08-17
"""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    import argparse

    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-08-17")
    args = ap.parse_args()
    local_root = Path(__file__).resolve().parents[1]
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=os.environ["EDGE_VPS_PASS"], timeout=60, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    for rel in (
        "app/paper_e2e.py",
        "app/books/adapters.py",
        "app/brokers/dhan/contracts.py",
        "app/auto_engine.py",
        "app/oms.py",
    ):
        sftp.put(str(local_root / rel), f"{CHROOT}{DESK}/{rel}")
    sftp.close()
    cmd = (
        f"chroot {CHROOT} bash -lc "
        f"'cd {DESK} && /root/Options-Edge-Lab/.venv/bin/python3 -m app.paper_e2e {args.day}'"
    )
    _, o, e = c.exec_command(cmd, timeout=300)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-1500:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
