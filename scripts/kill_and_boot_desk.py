#!/usr/bin/env python3
import os
import time

import paramiko

PASS = os.environ["EDGE_VPS_PASS"]
KEY = os.environ.get("DESK_API_KEY", "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c=")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("87.232.72.137", username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)


def run(cmd: str) -> str:
    _, o, e = c.exec_command(cmd, timeout=60)
    out = o.read().decode() + e.read().decode()
    print(out)
    return out


run("ss -ltnp | grep 8080 || true; ps aux | grep -E 'uvicorn|boot_desk' | grep -v grep")
run("fuser -k 8080/tcp 2>/dev/null; pkill -9 -f 'uvicorn app.main' 2>/dev/null; sleep 2")
run("ss -ltnp | grep 8080 || echo FREE")
run(
    "chroot /mnt/sys /root/Options-Edge-Lab/.venv/bin/python3 /root/Options-Edge-Desk/scripts/boot_desk.py"
)
time.sleep(4)
run("ss -ltnp | grep 8080 || true")
run("curl -s http://127.0.0.1:8080/healthz; echo")
run(
    f"curl -s -H 'X-API-Key: {KEY}' http://127.0.0.1:8080/api/v1/desk/system/token; echo"
)
run("tail -n 40 /mnt/sys/root/Options-Edge-Desk/logs/desk.out")
c.close()
