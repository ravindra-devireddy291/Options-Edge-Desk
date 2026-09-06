#!/usr/bin/env python3
"""Fix corrupted VPS .env with local PIN/TOTP (no mint)."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]
KEY = os.environ.get("DESK_API_KEY", "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c=")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"


def parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


merged: dict[str, str] = {}
for p in (
    Path(r"D:\Options-Nifty-Edge-Lab\.env"),
    Path(r"D:\Options-Edge-Desk\.env"),
):
    for k, v in parse(p).items():
        if v and k.startswith("DHAN_") and k not in merged:
            merged[k] = v

vals = {
    "DESK_API_KEY": KEY,
    "DESK_MODE": "paper",
    "DHAN_CLIENT_ID": merged.get("DHAN_CLIENT_ID", ""),
    "DHAN_PIN": merged.get("DHAN_PIN", ""),
    "DHAN_TOTP_SECRET": merged.get("DHAN_TOTP_SECRET", ""),
    "DHAN_ACCESS_TOKEN": "",
    "NIFTY_LAB_ROOT": "/root/Options-Nifty-Edge-Lab",
    "BN_LAB_ROOT": "/root/Options-Edge-Lab",
    "NIFTY_CONFIG": "config/rungs/nifty_alpha.yaml",
    "BN_CONFIG": "config/rungs/bn_alpha.yaml",
    "LIVE_NIFTY": "0",
    "LIVE_BANKNIFTY": "0",
}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file(f"{CHROOT}{DESK}/.env", "w") as fh:
    for k, v in vals.items():
        fh.write(f"{k}={v}\n")
sftp.close()
print(
    "vps env restored",
    f"pin_len={len(vals['DHAN_PIN'])}",
    f"totp_len={len(vals['DHAN_TOTP_SECRET'])}",
)
# verify no corruption
_, o, _ = c.exec_command(
    f"chroot {CHROOT} python3 -c \"from pathlib import Path; t=Path('{DESK}/.env').read_text(); print('bad' if '{{k}}' in t else 'ok'); print([l.split('=',1)[0] for l in t.splitlines() if '=' in l])\""
)
print(o.read().decode())
c.close()
