"""Check VPS paper archive + current runner/mock status."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko


def load_env() -> None:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    load_env()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        os.environ.get("EDGE_VPS_HOST", "87.232.72.137"),
        username="root",
        password=os.environ["EDGE_VPS_PASS"],
        timeout=45,
        allow_agent=False,
        look_for_keys=False,
    )
    cmds = [
        "chroot /mnt/sys ls -la /root/Options-Edge-Desk/data/paper/ 2>&1",
        "chroot /mnt/sys ls -la /root/Options-Edge-Desk/data/audit/ 2>&1 | tail -20",
        "chroot /mnt/sys cat /root/Options-Edge-Desk/data/trading_state.json 2>&1",
        "chroot /mnt/sys python3 -c \"import json,os; p='/root/Options-Edge-Desk/data/paper'; print(os.listdir(p) if os.path.isdir(p) else 'NO_DIR')\"",
        "chroot /mnt/sys bash -lc 'wc -c /root/Options-Edge-Desk/data/paper/*.json 2>/dev/null; head -c 800 /root/Options-Edge-Desk/data/paper/2026-08-17.json 2>/dev/null || echo NO_TODAY_JSON'",
        "systemctl is-active edge-desk; ss -ltnp | grep 8080 || true",
    ]
    for cmd in cmds:
        print("===", cmd[:90])
        _, o, e = c.exec_command(cmd, timeout=30)
        print((o.read() + e.read()).decode("utf-8", "replace")[:2500])
    c.close()


if __name__ == "__main__":
    main()
