#!/usr/bin/env python3
"""Promote Groww BN Alpha/Stable freeze to VPS + replay match + desk CLIENT_FREEZE.

1. Push BN YAMLs + brakes + g5 + replay script
2. Replay both packs on data_lake_groww (Nifty compound_book)
3. Fetch harvest to desk
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
BN_LAB = Path(r"D:\Options-Edge-Lab")
NIFTY_LAB = Path(r"D:\Options-Nifty-Edge-Lab")


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PORT = int(os.environ.get("EDGE_VPS_PORT", "443"))
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")

BN = "/root/Options-Edge-Lab"
NIFTY = "/root/Options-Nifty-Edge-Lab"
DESK_R = "/root/Options-Edge-Desk"
LAKE = f"{NIFTY}/data_lake_groww"
PY = f"{NIFTY}/.venv/bin/python3"


def _connect() -> paramiko.SSHClient:
    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST, port=PORT, username=USER, password=PASS, timeout=90,
        allow_agent=False, look_for_keys=False,
    )
    return c


def _run(c: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str]:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    print(f"[{code}] {cmd[:160]}\n{out[-3000:]}", flush=True)
    return code, out


def main() -> int:
    c = _connect()
    sftp = c.open_sftp()

    uploads = [
        (BN_LAB / "config/rungs/bn_alpha.yaml", f"{BN}/config/rungs/bn_alpha.yaml"),
        (BN_LAB / "config/rungs/bn_stable.yaml", f"{BN}/config/rungs/bn_stable.yaml"),
        (
            BN_LAB / "config/rungs/archive/bn_alpha_dhan_20260901.yaml",
            f"{BN}/config/rungs/archive/bn_alpha_dhan_20260901.yaml",
        ),
        (
            BN_LAB / "config/rungs/archive/bn_stable_dhan_20260901.yaml",
            f"{BN}/config/rungs/archive/bn_stable_dhan_20260901.yaml",
        ),
        (BN_LAB / "edge_lab/risk/execution_brakes.py", f"{BN}/edge_lab/risk/execution_brakes.py"),
        (ROOT / "scripts/replay_bn_groww_locked.py", f"{DESK_R}/scripts/replay_bn_groww_locked.py"),
        (ROOT / "reports/banknifty_enrich/g5_qa.json", f"{NIFTY}/reports/banknifty_enrich/g5_qa.json"),
        (ROOT / "reports/banknifty_enrich/g5_qa.json", f"{DESK_R}/reports/banknifty_enrich/g5_qa.json"),
        (ROOT / "reports/qa/CLIENT_FREEZE.md", f"{DESK_R}/reports/qa/CLIENT_FREEZE.md"),
    ]
    for src, dst in uploads:
        if not src.is_file():
            print("MISS", src, flush=True)
            continue
        parent = str(Path(dst).parent).replace("\\", "/")
        _run(c, f"mkdir -p {parent}", 30)
        sftp.put(str(src), dst)
        print("PUT", src.name, "->", dst, flush=True)

    _run(c, f"sed -i 's/\\r$//' {DESK_R}/scripts/replay_bn_groww_locked.py", 30)

    # Prefer Stable as BN_CONFIG for first paper week (stronger holdout).
    _run(
        c,
        "bash -lc 'grep -q BN_CONFIG /root/Options-Edge-Desk/.env 2>/dev/null && "
        "sed -i \"s|^BN_CONFIG=.*|BN_CONFIG=config/rungs/bn_stable.yaml|\" /root/Options-Edge-Desk/.env || "
        "echo BN_CONFIG=config/rungs/bn_stable.yaml >> /root/Options-Edge-Desk/.env; "
        "grep BN_CONFIG /root/Options-Edge-Desk/.env | tail -1'",
        60,
    )

    cmd = (
        f"bash -lc 'cd {NIFTY} && "
        f"export DATA_LAKE_ROOT={LAKE} "
        f"EDGE_LAB_ROOT={NIFTY} BN_LAB_ROOT={BN} PYTHONUNBUFFERED=1 "
        f"PYTHONPATH={NIFTY}:{DESK_R} && "
        f"{PY} -u {DESK_R}/scripts/replay_bn_groww_locked.py --all; echo REPLAY_RC=$?'"
    )
    print("=== VPS BN Groww replay ===", flush=True)
    code, _ = _run(c, cmd, timeout=7200)

    for rel in (
        "reports/qa/harvest/replay_bn_alpha_groww.json",
        "reports/qa/harvest/replay_bn_stable_groww.json",
        "reports/qa/harvest/replay_bn_groww_summary.json",
    ):
        try:
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(f"{DESK_R}/{rel}", str(dest))
            print("GET", rel, flush=True)
        except Exception as exc:
            print("GET_FAIL", rel, exc, flush=True)

    sftp.close()
    # soft restart desk so BN_CONFIG picks Stable
    _run(c, "systemctl restart edge-desk; sleep 2; systemctl is-active edge-desk; curl -sS http://127.0.0.1:8080/healthz || true", 90)
    c.close()
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
