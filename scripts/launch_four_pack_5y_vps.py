#!/usr/bin/env python3
"""Launch four locked 5Y compounds on the VPS (BN Alpha/Stable + Nifty Alpha/Stable).

Uses all cores: four parallel processes, nice'd so desk uvicorn stays up.
Does not place Dhan orders. Does not touch live flags.

  python scripts/launch_four_pack_5y_vps.py
  python scripts/launch_four_pack_5y_vps.py --status
  python scripts/launch_four_pack_5y_vps.py --fetch
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import paramiko

def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
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
LAKE = "/root/Options-Edge-Lab/data_lake"
BN_PY = f"{BN}/.venv/bin/python3"
NIFTY_PY = f"{NIFTY}/.venv/bin/python3"
SESSION = "four_pack_5y"
LOG = f"{BN}/reports/qa/harvest/four_pack_5y.log"
DONE = f"{BN}/reports/qa/harvest/four_pack_5y.done"
DESK = Path(__file__).resolve().parents[1]
BN_LOCAL = Path(r"D:\Options-Edge-Lab")
NIFTY_LOCAL = Path(r"D:\Options-Nifty-Edge-Lab")

UPLOAD = [
    (BN_LOCAL, BN, "scripts/replay_locked_5y.py"),
    (BN_LOCAL, BN, "config/rungs/bn_alpha.yaml"),
    (BN_LOCAL, BN, "config/rungs/bn_stable.yaml"),
    (NIFTY_LOCAL, NIFTY, "scripts/replay_locked_5y.py"),
    (NIFTY_LOCAL, NIFTY, "config/rungs/nifty_alpha.yaml"),
    (NIFTY_LOCAL, NIFTY, "config/rungs/nifty_stable.yaml"),
]
FETCH = [
    (f"{BN}/reports/qa/harvest/replay_bn_alpha.json", "replay_bn_alpha.json"),
    (f"{BN}/reports/qa/harvest/replay_bn_stable.json", "replay_bn_stable.json"),
    (f"{NIFTY}/reports/qa/harvest/replay_nifty_alpha.json", "replay_nifty_alpha.json"),
    (f"{NIFTY}/reports/qa/harvest/replay_nifty_stable.json", "replay_nifty_stable.json"),
    (f"{BN}/reports/qa/harvest/four_pack_5y.json", "four_pack_5y.json"),
    (LOG, "four_pack_5y.log"),
    (DONE, "four_pack_5y.done"),
]


def _connect() -> paramiko.SSHClient:
    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST, port=PORT, username=USER, password=PASS, timeout=90,
        banner_timeout=90, auth_timeout=90,
        allow_agent=False, look_for_keys=False,
    )
    return c


def _run(c: paramiko.SSHClient, cmd: str, timeout: int = 60) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    return (out + ("\n" + err if err else "")).strip()


def status(c: paramiko.SSHClient) -> None:
    print(f"host {HOST}:{PORT} tmux={_run(c, f'tmux ls 2>/dev/null | grep {SESSION} || echo NO_SESSION')}")
    load = _run(c, "cut -d ' ' -f1-3 /proc/loadavg")
    print(f"nproc={_run(c, 'nproc')} load={load}")
    print(f"desk={_run(c, 'systemctl is-active edge-desk')}")
    print(f"done={_run(c, f'test -f {DONE} && cat {DONE} || echo NO_DONE')}")
    print(f"log_tail:\n{_run(c, f'tail -n 30 {LOG} 2>/dev/null || echo no_log')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = _connect()

    if args.status or args.fetch:
        status(c)
        if args.fetch:
            local = DESK / "reports" / "qa" / "harvest"
            local.mkdir(parents=True, exist_ok=True)
            sftp = c.open_sftp()
            for remote, name in FETCH:
                dest = local / name
                try:
                    sftp.get(remote, str(dest))
                    print("OK", name, flush=True)
                except OSError as exc:
                    print("MISS", name, exc, flush=True)
            sftp.close()
        c.close()
        return 0

    sftp = c.open_sftp()
    for local_root, remote_root, rel in UPLOAD:
        src = local_root / rel
        if not src.exists():
            print("SKIP", rel, flush=True)
            continue
        _run(c, f"mkdir -p $(dirname {remote_root}/{rel})")
        sftp.put(str(src), f"{remote_root}/{rel}")
        print("UP", rel, flush=True)
    sftp.close()
    _run(
        c,
        f"sed -i 's/\\r$//' {BN}/scripts/replay_locked_5y.py {NIFTY}/scripts/replay_locked_5y.py",
    )

    cores = _run(c, "nproc")
    lake_ok = _run(c, f"test -d {LAKE} && echo LAKE_OK || echo LAKE_MISS")
    nifty_py = _run(c, f"test -x {NIFTY_PY} && echo {NIFTY_PY} || echo {BN_PY}")
    print(f"cores={cores} {lake_ok} nifty_py={nifty_py}", flush=True)
    if "LAKE_MISS" in lake_ok:
        c.close()
        raise SystemExit("data_lake missing on VPS")

    launcher = f"""#!/bin/bash
set -uo pipefail
export DATA_LAKE_ROOT={LAKE}
mkdir -p {BN}/reports/qa/harvest {NIFTY}/reports/qa/harvest
rm -f {DONE} {BN}/reports/qa/harvest/replay_bn_*.json {NIFTY}/reports/qa/harvest/replay_nifty_*.json
echo "=== FOUR PACK 5Y start $(date -Is) nproc=$(nproc) ==="
BN_PY={BN_PY}
NIFTY_PY={nifty_py}
run_one() {{
  lab="$1"; py="$2"; pack="$3"; out="$4"
  echo "=== LAUNCH $pack ==="
  cd "$lab"
  PYTHONPATH="$lab" nice -n 10 "$py" scripts/replay_locked_5y.py --pack "$pack" --lake {LAKE} --out "$out"
  echo EXIT_$pack $?
}}
run_one {BN} "$BN_PY" bn_alpha {BN}/reports/qa/harvest/replay_bn_alpha.json &
run_one {BN} "$BN_PY" bn_stable {BN}/reports/qa/harvest/replay_bn_stable.json &
run_one {NIFTY} "$NIFTY_PY" nifty_alpha {NIFTY}/reports/qa/harvest/replay_nifty_alpha.json &
run_one {NIFTY} "$NIFTY_PY" nifty_stable {NIFTY}/reports/qa/harvest/replay_nifty_stable.json &
wait
"$BN_PY" - <<'PY'
import json
from pathlib import Path
files = [
    Path("{BN}/reports/qa/harvest/replay_bn_alpha.json"),
    Path("{BN}/reports/qa/harvest/replay_bn_stable.json"),
    Path("{NIFTY}/reports/qa/harvest/replay_nifty_alpha.json"),
    Path("{NIFTY}/reports/qa/harvest/replay_nifty_stable.json"),
]
rows = []
ok = True
for p in files:
    if not p.exists():
        rows.append({{"pack": p.stem, "match": False, "error": "missing"}})
        ok = False
        continue
    r = json.loads(p.read_text())
    rows.append(r)
    ok = ok and bool(r.get("match"))
out = {{"all_match": ok, "rows": rows}}
Path("{BN}/reports/qa/harvest/four_pack_5y.json").write_text(json.dumps(out, indent=2))
print("ALL_MATCH", ok)
for r in rows:
    print(r.get("pack"), "match="+str(r.get("match")), r.get("got"))
PY
echo "=== FOUR PACK 5Y done $(date -Is) ==="
echo EXIT_$? > {DONE}
"""
    _run(c, f"mkdir -p {BN}/reports/qa/harvest /tmp")
    sftp = c.open_sftp()
    with sftp.file("/tmp/four_pack_5y.sh", "w") as fh:
        fh.write(launcher.replace("\r\n", "\n"))
    sftp.close()
    _run(c, "sed -i 's/\\r$//' /tmp/four_pack_5y.sh; chmod +x /tmp/four_pack_5y.sh")
    _run(c, f"tmux kill-session -t {SESSION} 2>/dev/null || true")
    _run(
        c,
        f"tmux new-session -d -s {SESSION} 'bash /tmp/four_pack_5y.sh > {LOG} 2>&1'",
    )
    print("launched tmux:" + SESSION, flush=True)
    status(c)
    c.close()
    print("status: python scripts/launch_four_pack_5y_vps.py --status", flush=True)
    print("fetch:  python scripts/launch_four_pack_5y_vps.py --fetch", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
