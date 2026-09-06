"""One-shot: SSH :443 and write DESK_BFF_SECRET to data/ (gitignored). Do not print the value."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()
    host = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
    port = int(os.environ.get("EDGE_VPS_PORT", "443"))
    user = os.environ.get("EDGE_VPS_USER", "root")
    pw = os.environ.get("EDGE_VPS_PASS", "")
    if not pw:
        print("Set EDGE_VPS_PASS", file=sys.stderr)
        return 1
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, port=port, username=user, password=pw, timeout=60, allow_agent=False, look_for_keys=False)
    _, o, e = c.exec_command("grep -E '^DESK_BFF_SECRET=' /root/Options-Edge-Desk/.env || true")
    raw = o.read().decode("utf-8", "replace").strip()
    err = e.read().decode("utf-8", "replace").strip()
    c.close()
    val = ""
    if raw.startswith("DESK_BFF_SECRET="):
        val = raw.split("=", 1)[1].strip().strip('"').strip("'")
    dest = ROOT / "data" / "_vercel_desk_bff_secret.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not val:
        print(f"missing DESK_BFF_SECRET on VPS err={err[:200]!r} raw_len={len(raw)}")
        return 2
    dest.write_text(val + "\n", encoding="utf-8")
    print(f"ok ssh {host}:{port} secret_chars={len(val)} wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
