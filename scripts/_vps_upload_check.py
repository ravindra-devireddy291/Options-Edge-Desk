"""Upload remote_live_api.py and run VPS lab checks."""
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
    host = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
    pw = os.environ["EDGE_VPS_PASS"]
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username="root", password=pw, timeout=45, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    sftp.put("scripts/_remote_live_api.py", "/mnt/sys/root/Options-Edge-Desk/scripts/_remote_live_api.py")
    sftp.close()
    cmds = [
        "chroot /mnt/sys bash -lc '/root/Options-Edge-Lab/.venv/bin/python3 /root/Options-Edge-Desk/scripts/_remote_live_api.py'",
        "chroot /mnt/sys ls -la /root/Options-Nifty-Edge-Lab/scripts/run_shadow_daily.py /root/Options-Edge-Lab/scripts/run_shadow_daily.py 2>&1",
        "chroot /mnt/sys ls /root/Options-Nifty-Edge-Lab/scripts/ 2>&1 | head -25",
        "chroot /mnt/sys ls /root/Options-Edge-Lab/scripts/ 2>&1 | head -25",
        "chroot /mnt/sys systemctl list-units --type=service --all 2>/dev/null | grep -i edge || true",
    ]
    for cmd in cmds:
        print("\n===", cmd[:90], "===")
        _, o, e = c.exec_command(cmd, timeout=45)
        print(o.read().decode()[:2500])
        err = e.read().decode()
        if err.strip():
            print("[stderr]", err[:400])
    c.close()


if __name__ == "__main__":
    main()
