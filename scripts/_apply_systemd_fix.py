"""Apply fixed edge-desk systemd unit and restore services."""
from pathlib import Path
import os, paramiko

HOST_SERVICE = Path("deploy/edge-desk-host.service").read_text(encoding="utf-8")

for line in Path(".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get("EDGE_VPS_HOST", "87.232.72.137"), username="root", password=os.environ["EDGE_VPS_PASS"], timeout=45, allow_agent=False, look_for_keys=False)

sftp = c.open_sftp()
with sftp.file("/etc/systemd/system/edge-desk.service", "w") as fh:
    fh.write(HOST_SERVICE)
sftp.close()

cmds = [
    "systemctl daemon-reload",
    "systemctl reset-failed edge-desk cloudflared 2>/dev/null || true",
    "systemctl restart edge-desk",
    "sleep 4; systemctl is-active edge-desk",
    "curl -s --max-time 10 http://127.0.0.1:8080/healthz; echo",
    "systemctl restart cloudflared",
    "sleep 4; systemctl is-active cloudflared",
    "ps aux | grep -E 'cloudflared|uvicorn' | grep -v grep",
    "ss -ltnp | grep 8080",
]
for cmd in cmds:
    print("===", cmd)
    _, o, e = c.exec_command(cmd, timeout=60)
    out = (o.read() + e.read()).decode("utf-8", errors="replace")
    print(out[:2000])
c.close()
