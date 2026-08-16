"""Install Cloudflare tunnel on the VPS HOST and point it at desk 127.0.0.1:8080.

Requires:
  EDGE_VPS_PASS
  CLOUDFLARE_TUNNEL_TOKEN   (from Zero Trust → Tunnels → install token)

Does not write the token into the git repo.
"""
from __future__ import annotations

import os
import sys

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ.get("EDGE_VPS_PASS", "")
TOKEN = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()


def run(c, cmd: str, timeout: int = 180) -> tuple[int, str]:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).encode("ascii", "replace").decode("ascii")
    code = o.channel.recv_exit_status()
    shown = cmd.replace(TOKEN, "<token>")
    print(f"[{code}] {shown[:160]}{'…' if len(shown) > 160 else ''}\n{out}\n---", flush=True)
    return code, out


def main() -> int:
    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")
    if not TOKEN:
        raise SystemExit("Set CLOUDFLARE_TUNNEL_TOKEN")
    if " " in TOKEN or "\n" in TOKEN:
        raise SystemExit("CLOUDFLARE_TUNNEL_TOKEN looks invalid")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    run(c, "ss -ltnp | grep 8080 || echo 'WARN: nothing on 127.0.0.1:8080'")
    run(c, "cat /etc/os-release | head -n 5")
    run(c, "command -v cloudflared && cloudflared --version || echo 'cloudflared not installed yet'")

    install = r"""
set -e
if ! command -v cloudflared >/dev/null 2>&1; then
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y cloudflared
fi
cloudflared --version
"""
    code, _ = run(c, install, timeout=180)
    if code != 0:
        print("apt install failed — trying GitHub amd64 .deb", flush=True)
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

    # Remotely managed tunnel: one systemd unit. Do not also run `tunnel run` (duplicate).
    run(c, "systemctl stop cloudflared 2>/dev/null || true; cloudflared service uninstall 2>/dev/null || true")
    # token only on the remote command line for install; not stored in this repo
    code, out = run(c, f"cloudflared service install {TOKEN}", timeout=60)
    if code != 0 and "already" not in out.lower():
        c.close()
        return 1
    run(c, "systemctl enable cloudflared; systemctl restart cloudflared; sleep 2; systemctl is-active cloudflared; systemctl --no-pager -l status cloudflared | head -n 25")
    run(c, "journalctl -u cloudflared -n 40 --no-pager || true")
    c.close()
    print(
        "Host tunnel service started. In Cloudflare Zero Trust → Tunnels → Public Hostname, "
        "add HTTP service http://127.0.0.1:8080 for REST+WS on the same hostname.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
