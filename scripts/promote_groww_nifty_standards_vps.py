#!/usr/bin/env python3
"""Promote Groww Nifty Alpha/Stable to client freeze on VPS.

1. Push updated YAMLs + replay/export/brakes
2. Replay locked 5y on data_lake_groww
3. Export client trade tapes
4. Fetch tapes + replay harvest to desk
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
LAB = Path(r"D:\Options-Nifty-Edge-Lab")


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
NIFTY = "/root/Options-Nifty-Edge-Lab"
LAKE = f"{NIFTY}/data_lake_groww"
PY = f"{NIFTY}/.venv/bin/python3"

FILES = [
    "config/rungs/nifty_alpha.yaml",
    "config/rungs/nifty_stable.yaml",
    "config/rungs/paper_2l_nifty_tier2_recommended.yaml",
    "config/rungs/paper_2l_nifty_ce400_secondary.yaml",
    "edge_lab/risk/execution_brakes.py",
    "scripts/replay_locked_5y.py",
    "scripts/export_nifty_trade_tape.py",
]

FETCH = [
    "reports/nifty_trades_tier2_recommended_2l.json",
    "reports/nifty_trades_ce400_secondary_2l.json",
    "reports/nifty_trades_standards_index.json",
    "reports/qa/harvest/replay_nifty_summary.json",
]


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
    print(f"[{code}] {cmd[:140]}\n{out[-2500:]}", flush=True)
    return code, out


def main() -> int:
    c = _connect()
    sftp = c.open_sftp()
    for rel in FILES:
        lp = LAB / rel
        if not lp.is_file():
            print("MISSING", rel, flush=True)
            continue
        rp = f"{NIFTY}/{rel}"
        parent = str(Path(rel).parent).replace("\\", "/")
        _run(c, f"mkdir -p {NIFTY}/{parent}", 30)
        sftp.put(str(lp), rp)
        print("PUT", rel, flush=True)

    g5 = ROOT / "reports" / "nifty_enrich" / "g5_qa.json"
    if g5.is_file():
        rp = f"{NIFTY}/reports/nifty_enrich/g5_qa.json"
        _run(c, f"mkdir -p {NIFTY}/reports/nifty_enrich {NIFTY}/reports/qa/harvest", 30)
        sftp.put(str(g5), rp)
        print("PUT g5_qa.json", flush=True)

    cmd = (
        f"bash -lc 'cd {NIFTY} && export DATA_LAKE_ROOT={LAKE} && "
        f"{PY} -u scripts/replay_locked_5y.py --all; echo REPLAY_RC=$?; "
        f"{PY} -u scripts/export_nifty_trade_tape.py --standards --lake {LAKE}; "
        f"echo EXPORT_RC=$?'"
    )
    print("=== VPS replay + export (Groww lake) ===", flush=True)
    code, _ = _run(c, cmd, timeout=3600)

    for rel in FETCH:
        rp = f"{NIFTY}/{rel}"
        try:
            dest = LAB / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(rp, str(dest))
            if rel.endswith(".json") and "nifty_trades_" in rel:
                d2 = ROOT / rel
                d2.parent.mkdir(parents=True, exist_ok=True)
                sftp.get(rp, str(d2))
            print("GET", rel, flush=True)
        except Exception as exc:
            print("MISS", rel, exc, flush=True)

    sftp.close()
    c.close()
    return 0 if code == 0 else code


if __name__ == "__main__":
    raise SystemExit(main())
