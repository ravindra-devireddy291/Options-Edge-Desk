"""Diagnose Cloudflare 502: desk process + port + tunnel."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko


def load_env() -> None:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 45) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace")
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        out += "\n[stderr]\n" + err.strip()
    return out


def main() -> None:
    load_env()
    host = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username="root", password=os.environ["EDGE_VPS_PASS"], timeout=45, allow_agent=False, look_for_keys=False)

    checks = [
        ("ss_listeners", "ss -ltnp | grep -E ':8080|:8000|:80' || echo NO_MATCH"),
        ("ps_uvicorn", "ps aux | grep -E 'uvicorn|app.main' | grep -v grep || echo NO_UVICORN"),
        ("curl_8080", "curl -s -o /dev/null -w 'http_code=%{http_code} time=%{time_total}s\\n' --max-time 8 http://127.0.0.1:8080/healthz 2>&1 || echo CURL_8080_FAIL"),
        ("curl_8000", "curl -s -o /dev/null -w 'http_code=%{http_code} time=%{time_total}s\\n' --max-time 8 http://127.0.0.1:8000/healthz 2>&1 || echo CURL_8000_FAIL"),
        ("chroot_curl_8080", "chroot /mnt/sys curl -s -o /dev/null -w 'http_code=%{http_code}\\n' --max-time 8 http://127.0.0.1:8080/healthz 2>&1 || echo CHROOT_8080_FAIL"),
        ("systemd_edge", "systemctl is-active edge-desk 2>&1; systemctl status edge-desk --no-pager -l 2>&1 | head -25"),
        ("cloudflared_ps", "ps aux | grep cloudflared | grep -v grep || echo NO_CLOUDFLARED"),
        ("desk_log_tail", "chroot /mnt/sys tail -40 /root/Options-Edge-Desk/logs/desk.out 2>/dev/null || echo NO_LOG"),
        ("tunnel_config", "cat /etc/cloudflared/config.yml 2>/dev/null || cat /root/.cloudflared/config.yml 2>/dev/null || ls -la /etc/cloudflared/ /root/.cloudflared/ 2>&1"),
    ]
    for name, cmd in checks:
        print(f"\n{'='*60}\n{name}\n{'='*60}")
        print(run(c, cmd))

    c.close()


if __name__ == "__main__":
    main()
