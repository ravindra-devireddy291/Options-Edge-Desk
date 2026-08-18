#!/usr/bin/env python3
"""Harden VPS: systemd auto-restart for desk, remove quick tunnel, restart named tunnel."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"
PY = "/root/Options-Edge-Lab/.venv/bin/python3"
BOOT = f"{DESK}/scripts/boot_desk.py"

HOST_SERVICE = """[Unit]
Description=Options Edge Desk (Dhan FastAPI :8080 in chroot)
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/sbin/chroot /mnt/sys {py} {boot}
Restart=always
RestartSec=5
StandardOutput=append:/mnt/sys/root/Options-Edge-Desk/logs/desk.out
StandardError=append:/mnt/sys/root/Options-Edge-Desk/logs/desk.out

[Install]
WantedBy=multi-user.target
""".format(py=PY, boot=BOOT)


def load_env() -> None:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str]:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace") + e.read().decode("utf-8", errors="replace")
    out = out.encode("ascii", errors="replace").decode("ascii")
    code = o.channel.recv_exit_status()
    print(f"[{code}] {cmd[:120]}{'…' if len(cmd) > 120 else ''}\n{out}\n---", flush=True)
    return code, out


def main() -> int:
    load_env()
    pw = os.environ.get("EDGE_VPS_PASS", "").strip()
    if not pw:
        raise SystemExit("Set EDGE_VPS_PASS")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=pw, timeout=60, allow_agent=False, look_for_keys=False)

    # 1. Stop duplicate quick tunnel (named tunnel stays via systemd cloudflared)
    run(c, "pkill -f 'cloudflared tunnel --url' || true; sleep 1")
    run(c, "ps aux | grep cloudflared | grep -v grep || echo NO_CLOUDFLARED")

    # 2. Kill manual nohup desk so systemd can bind :8080
    run(
        c,
        r"""python3 - <<'PY'
import os, re, signal, subprocess, time
out = subprocess.check_output(['ss', '-ltnp'], text=True)
pids = set()
for line in out.splitlines():
    if ':8080' in line:
        pids.update(int(x) for x in re.findall(r'pid=(\d+)', line))
print('8080 pids', sorted(pids))
for pid in pids:
    try:
        os.kill(pid, signal.SIGTERM)
        print('sigterm', pid)
    except ProcessLookupError:
        pass
time.sleep(2)
for pid in list(pids):
    try:
        os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
        print('sigkill', pid)
    except ProcessLookupError:
        pass
PY""",
        timeout=60,
    )

    # 3. Install host systemd unit (chroot boot — host systemd has no bus inside chroot)
    sftp = c.open_sftp()
    remote_svc = "/etc/systemd/system/edge-desk.service"
    with sftp.file(remote_svc, "w") as fh:
        fh.write(HOST_SERVICE)
    sftp.close()

    run(c, f"mkdir -p {CHROOT}{DESK}/logs")
    run(c, "systemctl daemon-reload")
    run(c, "systemctl enable edge-desk")
    run(c, "systemctl restart edge-desk")
    run(c, "sleep 3; systemctl is-active edge-desk; systemctl --no-pager -l status edge-desk | head -20")

    # 4. Restart named cloudflared for a clean connector
    run(c, "systemctl restart cloudflared")
    run(c, "sleep 3; systemctl is-active cloudflared; systemctl --no-pager -l status cloudflared | head -15")

    # 5. Verify
    run(c, "ss -ltnp | grep 8080 || true")
    run(c, "curl -s --max-time 10 http://127.0.0.1:8080/healthz; echo")
    run(c, "ps aux | grep -E 'cloudflared|uvicorn|boot_desk' | grep -v grep || true")

    c.close()
    print("VPS hardening complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
