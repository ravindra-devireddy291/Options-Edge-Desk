"""Install Cloudflare tunnel on the VPS HOST and point it at desk 127.0.0.1:8080.

Requires:
  EDGE_VPS_PASS
  CLOUDFLARE_TUNNEL_TOKEN   (from Zero Trust → Tunnels → install token)

Does not write the token into the git repo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PORT = int(os.environ.get("EDGE_VPS_PORT", "443"))
PASS = os.environ.get("EDGE_VPS_PASS", "")
TOKEN = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
HOST = os.environ.get("EDGE_VPS_HOST", HOST)
PORT = int(os.environ.get("EDGE_VPS_PORT", str(PORT)))
PASS = os.environ.get("EDGE_VPS_PASS", PASS)
TOKEN = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", TOKEN).strip()


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
    c.connect(HOST, port=PORT, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

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

    # Remotely managed tunnel: systemd unit + token file (new cloudflared expects --token-file).
    run(c, "systemctl stop cloudflared 2>/dev/null || true; pkill -f 'cloudflared tunnel --url' || true; sleep 1")
    run(c, "cloudflared service uninstall 2>/dev/null || true")
    run(c, "mkdir -p /etc/cloudflared; chmod 700 /etc/cloudflared")
    sftp = c.open_sftp()
    with sftp.file("/etc/cloudflared/token", "w") as fh:
        fh.write(TOKEN + "\n")
    sftp.chmod("/etc/cloudflared/token", 0o600)
    unit_path = Path(__file__).resolve().parents[1] / "deploy" / "cloudflared.service"
    unit = unit_path.read_text(encoding="utf-8")
    with sftp.file("/etc/systemd/system/cloudflared.service", "w") as fh:
        fh.write(unit)
    sftp.close()
    run(
        c,
        "test -x /usr/bin/cloudflared || ln -sf /usr/local/bin/cloudflared /usr/bin/cloudflared; "
        "systemctl daemon-reload; systemctl enable cloudflared; systemctl reset-failed cloudflared; "
        "systemctl restart cloudflared; sleep 8; systemctl is-active cloudflared; "
        "systemctl --no-pager -l status cloudflared | head -n 25",
        timeout=90,
    )
    run(c, "journalctl -u cloudflared -n 30 --no-pager || true")
    run(
        c,
        "curl -sS -m 20 -w '\\nHTTP=%{http_code}\\n' https://deskapi.ravindra-devireddy.com/healthz | tail -5",
        timeout=40,
    )
    c.close()
    print(
        "Named tunnel connector started. Public hostname should be "
        "deskapi.ravindra-devireddy.com → http://127.0.0.1:8080",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
