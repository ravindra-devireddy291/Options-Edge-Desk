#!/usr/bin/env python3
"""Restart edge-desk + cloudflared on VPS when deskapi returns Cloudflare 1033/502."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PORT = int(os.environ.get("EDGE_VPS_PORT", "443"))


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str]:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace") + e.read().decode("utf-8", errors="replace")
    code = o.channel.recv_exit_status()
    print(f"[{code}] {cmd}\n{out}\n---", flush=True)
    return code, out


def main() -> int:
    load_env()
    pw = os.environ.get("EDGE_VPS_PASS", "").strip()
    if not pw:
        print("Set EDGE_VPS_PASS in Options-Edge-Desk/.env", file=sys.stderr)
        return 1
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(HOST, port=PORT, username="root", password=pw, timeout=60, allow_agent=False, look_for_keys=False)
    except Exception as exc:
        print(f"SSH failed ({HOST}:{PORT}): {exc}", file=sys.stderr)
        print("Fix SSH/firewall, then re-run: py -3 scripts/restart_public_tunnel_vps.py", file=sys.stderr)
        return 1

    run(c, "systemctl restart edge-desk; sleep 3; systemctl is-active edge-desk")
    run(c, "curl -s -o /dev/null -w 'local_8080=%{http_code}\\n' --max-time 5 http://127.0.0.1:8080/healthz")
    run(c, "systemctl restart cloudflared; sleep 4; systemctl is-active cloudflared")
    run(c, "journalctl -u cloudflared -n 15 --no-pager || true")
    c.close()
    print("Then smoke: curl https://deskapi.ravindra-devireddy.com/healthz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
