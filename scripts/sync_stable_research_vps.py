#!/usr/bin/env python3
"""Fix VPS desk .env + sync locked research tapes + redeploy auth."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"

LOCAL_DESK = Path(__file__).resolve().parents[1]
NIFTY = Path(os.environ.get("NIFTY_LAB_ROOT", r"D:\Options-Nifty-Edge-Lab"))
BN = Path(os.environ.get("BN_LAB_ROOT", r"D:\Options-Edge-Lab"))

UPLOADS = [
    (
        NIFTY / "reports" / "nifty_trades_tier1_conservative_2l.json",
        f"{CHROOT}/root/Options-Nifty-Edge-Lab/reports/nifty_trades_tier1_conservative_2l.json",
    ),
    (
        NIFTY / "reports" / "nifty_trades_tier2_recommended_2l.json",
        f"{CHROOT}/root/Options-Nifty-Edge-Lab/reports/nifty_trades_tier2_recommended_2l.json",
    ),
    (
        BN / "reports" / "live_freeze_2l_honest.json",
        f"{CHROOT}/root/Options-Edge-Lab/reports/live_freeze_2l_honest.json",
    ),
    (
        LOCAL_DESK / "app" / "auth.py",
        f"{CHROOT}{DESK}/app/auth.py",
    ),
    (
        LOCAL_DESK / "app" / "research" / "stable.py",
        f"{CHROOT}{DESK}/app/research/stable.py",
    ),
    (
        LOCAL_DESK / "app" / "main.py",
        f"{CHROOT}{DESK}/app/main.py",
    ),
]


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 120) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    print(out, flush=True)
    return out


FIX_ENV = r"""
from pathlib import Path
p = Path("/root/Options-Edge-Desk/.env")
t = p.read_text(encoding="utf-8")
# convert literal \n sequences if file was flattened
if t.count("\n") < 3 and "\\n" in t:
    t = t.replace("\\n", "\n")
    p.write_text(t, encoding="utf-8")
    print("rewrote literal newlines")
else:
    print("newlines ok", t.count(chr(10)))

lines = []
for line in p.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        lines.append(line)
        continue
    k, v = s.split("=", 1)
    k = k.strip()
    if k == "NIFTY_LAB_ROOT":
        lines.append("NIFTY_LAB_ROOT=/root/Options-Nifty-Edge-Lab")
    elif k == "BN_LAB_ROOT":
        lines.append("BN_LAB_ROOT=/root/Options-Edge-Lab")
    else:
        lines.append(f"{k}={v.strip().strip(chr(34)).strip(chr(39))}")
p.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
text = p.read_text(encoding="utf-8")
print("env_lines", len(text.splitlines()))
# print only key names
keys = [ln.split("=", 1)[0] for ln in text.splitlines() if "=" in ln and not ln.strip().startswith("#")]
print("keys", ",".join(keys))
"""


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    run(c, "findmnt /mnt/sys || (mkdir -p /mnt/sys && mount /dev/vdb1 /mnt/sys)")
    run(
        c,
        "mkdir -p "
        f"{CHROOT}/root/Options-Nifty-Edge-Lab/reports "
        f"{CHROOT}/root/Options-Edge-Lab/reports "
        f"{CHROOT}{DESK}/app/research",
    )

    sftp = c.open_sftp()
    for local, remote in UPLOADS:
        if not local.exists():
            print("skip missing", local, flush=True)
            continue
        sftp.put(str(local), remote)
        print("scp", local.name, "->", remote, flush=True)
    sftp.close()

    # write fix script remotely and execute inside chroot
    sftp = c.open_sftp()
    with sftp.file(f"{CHROOT}{DESK}/scripts/_fix_env.py", "w") as fh:
        fh.write(FIX_ENV)
    sftp.close()
    run(c, f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 {DESK}/scripts/_fix_env.py")

    # hard restart with boot_desk
    run(c, "fuser -k 8080/tcp 2>/dev/null || true; pkill -9 -f 'uvicorn app.main' 2>/dev/null || true; sleep 2")
    run(
        c,
        f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 {DESK}/scripts/boot_desk.py",
    )
    time.sleep(4)

    # extract key names only, then call research using key from fixed env inside chroot
    verify = r"""
from pathlib import Path
import json, urllib.request
env = {}
for line in Path("/root/Options-Edge-Desk/.env").read_text(encoding="utf-8").splitlines():
    line=line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k,v=line.split("=",1)
    env[k.strip()]=v.strip().strip('"').strip("'")
key=env.get("DESK_API_KEY","")
print("boot_check", "key_len", len(key), "nifty", env.get("NIFTY_LAB_ROOT"), "bn", env.get("BN_LAB_ROOT"))
req=urllib.request.Request(
    "http://127.0.0.1:8080/api/v1/desk/research/stable",
    headers={"X-API-Key": key},
)
with urllib.request.urlopen(req, timeout=30) as resp:
    data=json.loads(resp.read().decode())
print("ok", data.get("ok"))
payload=data.get("data") or {}
print("overall", payload.get("overall_most_stable"))
print("errors", payload.get("errors"))
ms=payload.get("most_stable") or {}
for u,p in ms.items():
    m=p.get("metrics") or {}
    print(u, p.get("pack_id"), "ret", m.get("return_pct"), "dd", m.get("peak_dd_pct"), "trades", m.get("n_trades"))
"""
    sftp = c.open_sftp()
    with sftp.file(f"{CHROOT}{DESK}/scripts/_verify_stable.py", "w") as fh:
        fh.write(verify)
    sftp.close()
    run(c, f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 {DESK}/scripts/_verify_stable.py")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
