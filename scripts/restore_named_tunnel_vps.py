#!/usr/bin/env python3
"""Restore production Cloudflare named tunnel (deskapi.ravindra-devireddy.com).

Add to Options-Edge-Desk/.env (never commit):
  CLOUDFLARE_TUNNEL_TOKEN=<from Zero Trust → Tunnels → Configure → install token>

Then:
  py -3 scripts/restore_named_tunnel_vps.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    token = ""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("CLOUDFLARE_TUNNEL_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not token:
        print(
            "Missing CLOUDFLARE_TUNNEL_TOKEN in Options-Edge-Desk/.env\n\n"
            "Cloudflare Zero Trust → Networks → Tunnels → (desk tunnel) → Configure\n"
            "→ copy the token from: cloudflared service install <TOKEN>\n",
            file=sys.stderr,
        )
        return 1
    script = Path(__file__).resolve().parent / "install_cloudflare_tunnel_vps.py"
    return subprocess.call([sys.executable, str(script)])


if __name__ == "__main__":
    raise SystemExit(main())
