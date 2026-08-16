"""Rebuild a multiline VPS desk .env from BN lab Dhan keys + a valid DESK_API_KEY."""
from __future__ import annotations

import os
import sys

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"
# Same default the UI/VPS scripts have used when DESK_API_KEY is not in laptop .env
KEY = os.environ.get("DESK_API_KEY") or "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c="

REMOTE = r"""
from pathlib import Path
desk = Path("/root/Options-Edge-Desk/.env")
bn = Path("/root/Options-Edge-Lab/.env")
vals = {
    "DESK_API_KEY": __KEY__,
    "DESK_MODE": "paper",
    "NIFTY_LAB_ROOT": "/root/Options-Nifty-Edge-Lab",
    "BN_LAB_ROOT": "/root/Options-Edge-Lab",
    "NIFTY_CONFIG": "config/rungs/paper_2l_nifty_tier2_recommended.yaml",
    "BN_CONFIG": "config/edge_book_2l_dd20.yaml",
    "LIVE_NIFTY": "0",
    "LIVE_BANKNIFTY": "0",
    "DESK_PAPER_AUTO": "1",
}
if bn.exists():
    for line in bn.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k in ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN", "DHAN_PIN", "DHAN_TOTP_SECRET") and v:
            vals[k] = v
desk.parent.mkdir(parents=True, exist_ok=True)
desk.write_text("\n".join(f"{k}={v}" for k, v in vals.items()) + "\n", encoding="utf-8")
print("wrote", desk, "nkeys", len(vals), "keynames", sorted(vals))
print("DESK_API_KEY_len", len(vals["DESK_API_KEY"]))
"""


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)
    helper = f"{CHROOT}{DESK}/scripts/_repair_env.py"
    body = REMOTE.replace("__KEY__", repr(KEY))
    sftp = c.open_sftp()
    with sftp.file(helper, "w") as fh:
        fh.write(body)
    sftp.close()
    py = "/root/Options-Edge-Lab/.venv/bin/python3"
    _, o, e = c.exec_command(f"chroot {CHROOT} bash -lc '{py} {DESK}/scripts/_repair_env.py'", timeout=30)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    sys.stderr.write(e.read().decode("utf-8", "replace"))
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
