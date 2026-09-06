#!/usr/bin/env python3
"""Install cloudflared binary on VPS (no token)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 180) -> tuple[int, str]:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    print(f"[{code}] {cmd[:120]}\n{out}\n---", flush=True)
    return code, out


def main() -> int:
    load_env()
    host = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
    port = int(os.environ.get("EDGE_VPS_PORT", "443"))
    pw = os.environ.get("EDGE_VPS_PASS", "").strip()
    if not pw:
        raise SystemExit("Set EDGE_VPS_PASS")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, port=port, username="root", password=pw, timeout=60, allow_agent=False, look_for_keys=False)

    install = r"""
set -e
if command -v cloudflared >/dev/null 2>&1; then
  cloudflared --version
  exit 0
fi
mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' > /etc/apt/sources.list.d/cloudflared.list
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y cloudflared
cloudflared --version
"""
    code, _ = run(c, install, timeout=300)
    if code != 0:
        run(
            c,
            r"""
set -e
ARCH=$(dpkg --print-architecture)
curl -fsSL -o /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
dpkg -i /tmp/cloudflared.deb || apt-get install -f -y
cloudflared --version
""",
            timeout=180,
        )
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
