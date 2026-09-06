#!/usr/bin/env python3
"""Confirm VPS desk has four-pack paper routing and healthz 200."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(c, cmd: str, timeout: int = 45) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode("utf-8", "replace").strip()


def main() -> int:
    _load_env()
    host = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
    port = int(os.environ.get("EDGE_VPS_PORT", "443"))
    user = os.environ.get("EDGE_VPS_USER", "root")
    pw = os.environ.get("EDGE_VPS_PASS", "")
    if not pw:
        raise SystemExit("Set EDGE_VPS_PASS")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, port=port, username=user, password=pw, timeout=60, allow_agent=False, look_for_keys=False)
    py = "/root/Options-Edge-Lab/.venv/bin/python3"
    checks = [
        "systemctl is-active edge-desk",
        "grep -c 'def desk_books' /root/Options-Edge-Desk/app/books/adapters.py",
        "curl -s --max-time 8 http://127.0.0.1:8080/healthz",
        (
            f"cd /root/Options-Edge-Desk && {py} -c "
            "'from app.runners.state import RUNNER; RUNNER.mode=\"paper\"; "
            "from app.books.adapters import desk_books; b=desk_books(); "
            "print(len(b), [x.pack_id for x in b])'"
        ),
    ]
    ok = True
    for cmd in checks:
        out = run(c, cmd)
        print(out[:600], flush=True)
        if cmd.endswith("healthz") and "ok" not in out.lower():
            ok = False
        if "desk_books" in cmd and "def desk_books" not in cmd and not out.startswith("4 "):
            ok = False
    c.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
