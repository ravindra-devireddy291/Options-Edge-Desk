#!/usr/bin/env python3
"""Deploy Options-Edge-Desk to VPS and install systemd unit.

  set EDGE_VPS_PASS=...
  python scripts/deploy_desk_vps.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")
if not PASS:
    raise SystemExit("Set EDGE_VPS_PASS")

CHROOT = "/mnt/sys"
REMOTE = "/root/Options-Edge-Desk"
LOCAL = Path(__file__).resolve().parents[1]
PY = "/root/Options-Edge-Lab/.venv/bin/python3"

FILES = [
    "requirements.txt",
    "README.md",
    ".env.example",
    "app/__init__.py",
    "app/auth.py",
    "app/main.py",
    "app/oms.py",
    "app/session.py",
    "app/triggers.py",
    "app/idempotency.py",
    "app/auto_engine.py",
    "app/desk_log.py",
    "app/schedule.py",
    "app/paper_archive.py",
    "app/mock/__init__.py",
    "app/mock/clock.py",
    "app/mock/tape_index.py",
    "app/mock/marks.py",
    "app/mock/ledger.py",
    "app/mock/engine.py",
    "app/brokers/__init__.py",
    "app/brokers/dhan/__init__.py",
    "app/brokers/dhan/client.py",
    "app/brokers/dhan/contracts.py",
    "app/books/__init__.py",
    "app/books/adapters.py",
    "app/books/shadow_oms.py",
    "app/research/__init__.py",
    "app/research/stable.py",
    "app/runners/__init__.py",
    "app/runners/state.py",
    "app/schemas/__init__.py",
    "app/schemas/envelope.py",
    "docs/MVP_UI_API.md",
    "docs/BACKEND_REQUIREMENTS.md",
    "docs/UI_API_CONTRACT.md",
    "docs/BACKEND_BUSINESS_LOGIC.md",
    "docs/MODE_SCENARIO_MATRIX.md",
    "docs/UI_COLLAB.md",
    "deploy/edge-desk.service",
    "deploy/nginx-desk.conf",
    "scripts/boot_desk.py",
]


def run(c, cmd: str, timeout: int = 180, check: bool = True) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    if check and code != 0:
        raise RuntimeError(f"{code}: {cmd}\n{out}\n{err}")
    return out + err


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=60, allow_agent=False, look_for_keys=False)
    run(c, "findmnt /mnt/sys || (mkdir -p /mnt/sys && mount /dev/vdb1 /mnt/sys)")
    run(c, f"mkdir -p {CHROOT}{REMOTE}/{{app/brokers/dhan,app/books,app/research,app/runners,app/schemas,app/mock,docs,deploy,data/audit,data/paper,scripts}}")
    run(
        c,
        f"mkdir -p {CHROOT}/root/Options-Nifty-Edge-Lab/reports/shadow "
        f"{CHROOT}/root/Options-Edge-Lab/reports/shadow",
        check=False,
    )

    sftp = c.open_sftp()
    for rel in FILES:
        local = LOCAL / rel
        if not local.exists():
            print("skip", rel, flush=True)
            continue
        remote = f"{CHROOT}{REMOTE}/{rel}"
        run(c, f"mkdir -p $(dirname {remote})", check=False)
        sftp.put(str(local), remote)
        print("scp", rel, flush=True)
    sftp.close()

    # ensure .env exists (do not overwrite secrets)
    run(
        c,
        f"test -f {CHROOT}{REMOTE}/.env || cp {CHROOT}{REMOTE}/.env.example {CHROOT}{REMOTE}/.env",
        check=False,
    )
    # merge desk paths + API key; pull Dhan creds from BN lab .env if present
    desk_key = os.environ.get("DESK_API_KEY", "").strip()
    merge_py = r"""
import os,re
from pathlib import Path
desk=Path('/root/Options-Edge-Desk/.env')
bn=Path('/root/Options-Edge-Lab/.env')
text=desk.read_text() if desk.exists() else ''
vals={}
for line in text.splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); vals[k.strip()]=v.strip()
want={
 'DESK_MODE':'paper',
 'NIFTY_LAB_ROOT':'/root/Options-Nifty-Edge-Lab',
 'BN_LAB_ROOT':'/root/Options-Edge-Lab',
 'NIFTY_CONFIG':'config/rungs/paper_2l_nifty_tier2_recommended.yaml',
 'BN_CONFIG':'config/edge_book_2l_dd20.yaml',
 'LIVE_NIFTY':'0',
 'LIVE_BANKNIFTY':'0',
 'DESK_PAPER_AUTO':'1',
}
key=os.environ.get('DESK_API_KEY','').strip()
if key: want['DESK_API_KEY']=key
elif not vals.get('DESK_API_KEY') or vals.get('DESK_API_KEY') in ('','change-me-desk-api-key'):
    want['DESK_API_KEY']='change-me-desk-api-key'
if bn.exists():
    for line in bn.read_text().splitlines():
        if line.startswith('DHAN_CLIENT_ID=') or line.startswith('DHAN_ACCESS_TOKEN='):
            k,v=line.split('=',1); want[k]=v.strip()
vals.update(want)
out=[]
for k,v in vals.items():
    out.append(f'{k}={v}')
desk.write_text('\n'.join(out)+'\n')
print('env keys', sorted(vals))
"""
    # write merge helper then run inside chroot with DESK_API_KEY
    sftp2 = c.open_sftp()
    helper = f"{CHROOT}{REMOTE}/scripts/_merge_env.py"
    with sftp2.file(helper, "w") as fh:
        fh.write(merge_py)
    sftp2.close()
    env_export = f"DESK_API_KEY={desk_key} " if desk_key else ""
    run(
        c,
        f"chroot {CHROOT} bash -lc '{env_export}{PY} {REMOTE}/scripts/_merge_env.py'",
        timeout=60,
        check=False,
    )
    run(
        c,
        f"chroot {CHROOT} bash -lc '{PY} -m pip install -q fastapi uvicorn pyyaml pydantic websockets python-dotenv tzdata'",
        timeout=300,
    )
    # Prefer systemd when available; otherwise nohup (this VPS uses chroot without host systemd)
    systemd_ok = run(
        c,
        f"chroot {CHROOT} bash -lc 'command -v systemctl >/dev/null && systemctl daemon-reload 2>/dev/null; echo SYSTEMD_OK'",
        check=False,
    )
    if "SYSTEMD_OK" in systemd_ok and "Failed to connect to bus" not in systemd_ok:
        run(
            c,
            f"cp {CHROOT}{REMOTE}/deploy/edge-desk.service {CHROOT}/etc/systemd/system/edge-desk.service; "
            f"chroot {CHROOT} bash -lc 'systemctl daemon-reload; systemctl enable edge-desk; systemctl restart edge-desk; "
            f"sleep 2; systemctl is-active edge-desk; curl -s http://127.0.0.1:8080/healthz || true'",
            timeout=120,
            check=False,
        )
    else:
        print("systemd unavailable — starting via Python env loader", flush=True)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from vps_desk_restart import restart_desk

        desk_key = os.environ.get("DESK_API_KEY", "").strip() or "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c="

        def _run(cmd: str, timeout: int = 120) -> str:
            return run(c, cmd, timeout=timeout, check=False)

        restart_desk(_run, desk_key)
    print(run(c, f"tail -n 30 {CHROOT}{REMOTE}/logs/desk.out 2>/dev/null || true", check=False), flush=True)
    c.close()
    print("deployed", REMOTE, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
