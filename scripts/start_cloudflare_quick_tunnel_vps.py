"""Start a Cloudflare *quick* tunnel on the VPS for dev (trycloudflare.com).

Named Zero Trust tunnel can stay installed for later when a domain exists.
This extra process only publishes http://127.0.0.1:8080 to a random HTTPS URL.
"""
from __future__ import annotations

import os
import re
import sys
import time

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ.get("EDGE_VPS_PASS", "")
LOG = "/var/log/cloudflared-quick.log"


def run(c, cmd: str, timeout: int = 60) -> tuple[int, str]:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    safe = out.encode("ascii", "replace").decode("ascii")
    print(f"[{code}] {cmd[:140]}\n{safe}\n---", flush=True)
    return code, out


def main() -> int:
    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    run(c, "ss -ltnp | grep 8080 || echo MISSING_8080")
    run(c, "pkill -f 'cloudflared tunnel --url' || true; sleep 1")
    run(
        c,
        f"nohup cloudflared tunnel --url http://127.0.0.1:8080 --no-autoupdate > {LOG} 2>&1 & echo pid=$!; sleep 8",
        timeout=30,
    )
    url = None
    for _ in range(8):
        _, out = run(c, f"tr -cd '\\11\\12\\15\\40-\\176' < {LOG} | tail -n 40")
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", out, re.I)
        if m:
            url = m.group(0).rstrip("/")
            break
        time.sleep(3)
    if not url:
        print("NO_URL_YET", flush=True)
        c.close()
        return 1
    print(f"QUICK_TUNNEL_URL={url}", flush=True)
    run(c, f"curl -sS -m 20 {url}/healthz; echo")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
