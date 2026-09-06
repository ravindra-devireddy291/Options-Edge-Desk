#!/usr/bin/env python3
"""Harden VPS for near-24/7 desk API availability.

Applies:
  - edge-desk.service  (Restart=always, StartLimitIntervalSec=0, network-online)
  - cloudflared.service (same + After=edge-desk)
  - desk-watchdog timer (every 2 min: restart if local/public healthz fails)

  set EDGE_VPS_PASS=...
  py -3 scripts/harden_uptime_vps.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PORT = int(os.environ.get("EDGE_VPS_PORT", "443"))
PASS = os.environ.get("EDGE_VPS_PASS", "").strip()


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str]:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    print(f"[{code}] {cmd[:140]}\n{out[:2200]}\n---", flush=True)
    return code, out


def main() -> int:
    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    sftp = c.open_sftp()
    puts = [
        ("deploy/edge-desk.service", "/etc/systemd/system/edge-desk.service"),
        ("deploy/cloudflared.service", "/etc/systemd/system/cloudflared.service"),
        ("deploy/desk-watchdog.sh", "/usr/local/bin/desk-watchdog.sh"),
        ("deploy/desk-watchdog.service", "/etc/systemd/system/desk-watchdog.service"),
        ("deploy/desk-watchdog.timer", "/etc/systemd/system/desk-watchdog.timer"),
    ]
    for rel, remote in puts:
        local = ROOT / rel
        data = local.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        with sftp.file(remote, "wb") as fh:
            fh.write(data)
        print("scp", rel, "->", remote, flush=True)
    sftp.chmod("/usr/local/bin/desk-watchdog.sh", 0o755)
    sftp.close()

    run(
        c,
        "systemctl daemon-reload; "
        "systemctl enable edge-desk cloudflared desk-watchdog.timer; "
        "systemctl restart edge-desk; sleep 4; "
        "systemctl restart cloudflared; sleep 6; "
        "systemctl restart desk-watchdog.timer; "
        "systemctl start desk-watchdog.service; "
        "systemctl is-enabled edge-desk cloudflared desk-watchdog.timer; "
        "systemctl is-active edge-desk cloudflared desk-watchdog.timer",
        timeout=90,
    )
    run(c, "/usr/local/bin/desk-watchdog.sh", timeout=60)
    run(
        c,
        "curl -sS -m 8 http://127.0.0.1:8080/healthz; echo; "
        "curl -sS -m 15 -w '\\nHTTP=%{http_code}\\n' https://deskapi.ravindra-devireddy.com/healthz | tail -5; "
        "systemctl list-timers desk-watchdog.timer --no-pager",
        timeout=40,
    )
    c.close()
    print("HA harden applied. Watchdog: journalctl -t desk-watchdog -f", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
