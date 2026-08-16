#!/usr/bin/env python3
"""Kill whatever is on :8080 and start the desk with Python-loaded .env (no bash source)."""
from __future__ import annotations

CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"
PY = "/root/Options-Edge-Lab/.venv/bin/python3"
BOOT = f"{DESK}/scripts/boot_desk.py"


def kill_desk(run) -> None:
    run("mountpoint -q /mnt/sys/proc || mount -t proc proc /mnt/sys/proc")
    run(
        "python3 - <<'PY'\n"
        "import os, re, signal, subprocess, time\n"
        "out = subprocess.check_output(['ss', '-ltnp'], text=True)\n"
        "pids = set()\n"
        "for line in out.splitlines():\n"
        "    if ':8080' in line:\n"
        "        pids.update(int(x) for x in re.findall(r'pid=(\\d+)', line))\n"
        "print('8080 pids', sorted(pids))\n"
        "for pid in pids:\n"
        "    try:\n"
        "        os.kill(pid, signal.SIGKILL)\n"
        "        print('killed', pid)\n"
        "    except ProcessLookupError:\n"
        "        pass\n"
        "os.system('pkill -9 -f uvicorn')\n"
        "os.system('fuser -k 8080/tcp >/dev/null 2>&1')\n"
        "time.sleep(2)\n"
        "left = subprocess.check_output(['ss', '-ltnp'], text=True)\n"
        "still = [ln for ln in left.splitlines() if ':8080' in ln]\n"
        "print('still_listening', still)\n"
        "PY"
    )


def start_desk(run, api_key: str) -> None:
    run(f"mkdir -p {CHROOT}{DESK}/logs")
    run(
        f"nohup chroot {CHROOT} {PY} {BOOT} "
        f">> {CHROOT}{DESK}/logs/desk.out 2>&1 & echo pid=$!; sleep 4; "
        f"ss -ltnp | grep 8080 || true; "
        f"curl -s http://127.0.0.1:8080/healthz; echo; "
        f"curl -s -H 'X-API-Key: {api_key}' http://127.0.0.1:8080/api/v1/desk/system/token; echo"
    )


def restart_desk(run, api_key: str) -> None:
    kill_desk(run)
    start_desk(run, api_key)
