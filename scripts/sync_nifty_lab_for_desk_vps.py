#!/usr/bin/env python3
"""Ensure Nifty Tier2 config + minimal lab packages exist on VPS for desk gates."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]
CHROOT = "/mnt/sys"
NIFTY = "/root/Options-Nifty-Edge-Lab"
LOCAL = Path(r"D:\Options-Nifty-Edge-Lab")

FILES = [
    "config/rungs/paper_2l_nifty_tier2_recommended.yaml",
    "config/rungs/paper_2l_nifty_tier1_conservative.yaml",
    "edge_lab/risk/execution_brakes.py",
    "edge_lab/risk/__init__.py",
    "edge_lab/__init__.py",
    "edge_lab/capital.py",
    "edge_lab/paths.py",
    "edge_lab/dhan_client.py",
]


def run(c, cmd: str, timeout: int = 60) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    print(f"[{o.channel.recv_exit_status()}] {cmd}\n{out}\n---", flush=True)
    return out


c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)
run(c, f"ls {CHROOT}{NIFTY} 2>&1 | head -30")
run(c, f"mkdir -p {CHROOT}{NIFTY}/{{config/rungs,edge_lab/risk,scripts,reports/shadow}}")
sftp = c.open_sftp()
for rel in FILES:
    lp = LOCAL / rel
    if not lp.exists():
        print("missing local", rel, flush=True)
        continue
    rp = f"{CHROOT}{NIFTY}/{rel}"
    run(c, f"mkdir -p $(dirname {rp})", timeout=30)
    sftp.put(str(lp), rp)
    print("scp", rel, flush=True)
sftp.close()
run(c, f"ls {CHROOT}{NIFTY}/config/rungs | head")
run(c, f"test -f {CHROOT}{NIFTY}/edge_lab/risk/execution_brakes.py && echo brakes_ok")
c.close()
