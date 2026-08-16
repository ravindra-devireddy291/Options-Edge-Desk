#!/usr/bin/env python3
"""Verify VPS TOTP keys exist and force generateAccessToken."""
from __future__ import annotations

import json
import os
import sys

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]
KEY = os.environ.get("DESK_API_KEY", "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c=")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"


def run(c, cmd: str, timeout: int = 90) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    print(f"[{o.channel.recv_exit_status()}] {cmd}\n{out}\n---", flush=True)
    return out


c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

# inspect env presence only
run(
    c,
    f"chroot {CHROOT} python3 - <<'PY'\n"
    "from pathlib import Path\n"
    f"p=Path('{DESK}/.env')\n"
    "vals={}\n"
    "for line in p.read_text().splitlines():\n"
    "  if '=' in line and not line.strip().startswith('#'):\n"
    "    k,v=line.split('=',1); vals[k.strip()]=v.strip()\n"
    "for k in ['DHAN_CLIENT_ID','DHAN_PIN','DHAN_TOTP_SECRET','DHAN_ACCESS_TOKEN']:\n"
    "  v=vals.get(k,'')\n"
    "  print(k, 'set' if v else 'EMPTY', 'len='+str(len(v)))\n"
    "PY",
)

# clear expired token so TOTP path is clean; keep pin/secret
run(
    c,
    f"chroot {CHROOT} python3 - <<'PY'\n"
    "from pathlib import Path\n"
    f"p=Path('{DESK}/.env')\n"
    "vals={}\n"
    "for line in p.read_text().splitlines():\n"
    "  if '=' in line and not line.strip().startswith('#'):\n"
    "    k,v=line.split('=',1); vals[k.strip()]=v.strip()\n"
    "vals['DHAN_ACCESS_TOKEN']=''\n"
    "p.write_text('\\n'.join(f'{{k}}={{v}}' for k,v in vals.items())+'\\n')\n"
    "print('cleared expired access token')\n"
    "PY",
)

run(c, "mountpoint -q /mnt/sys/proc || mount -t proc proc /mnt/sys/proc")
run(c, "fuser -k 8080/tcp 2>/dev/null || true; sleep 1")
run(
    c,
    f"nohup chroot {CHROOT} /bin/bash -c "
    f"'cd {DESK} && set -a && . {DESK}/.env && set +a && "
    f"export PYTHONPATH={DESK} && "
    f"echo PIN_LEN=${{#DHAN_PIN}} TOTP_LEN=${{#DHAN_TOTP_SECRET}} CLIENT=$DHAN_CLIENT_ID && "
    f"exec /root/Options-Edge-Lab/.venv/bin/python3 -m uvicorn app.main:app "
    f"--host 127.0.0.1 --port 8080' "
    f"> {CHROOT}{DESK}/logs/desk.out 2>&1 & sleep 4; "
    f"curl -s http://127.0.0.1:8080/healthz; echo",
)

# direct mint via API generate_now
body = json.dumps({"generate_now": True, "client_id": "1112040719"})
sftp = c.open_sftp()
with sftp.file("/tmp/mint.json", "w") as fh:
    fh.write(body)
sftp.close()

# use renew which calls ensure_fresh_token; also call a small python inside chroot
run(
    c,
    f"chroot {CHROOT} bash -lc '"
    f"cd {DESK}; set -a; . {DESK}/.env; set +a; export PYTHONPATH={DESK}; "
    f"/root/Options-Edge-Lab/.venv/bin/python3 - <<\"PY\"\n"
    "from app.brokers.dhan import client as dhan\n"
    "import os\n"
    "print('env pin', bool(os.environ.get('DHAN_PIN')), 'totp', bool(os.environ.get('DHAN_TOTP_SECRET')))\n"
    "try:\n"
    "  r=dhan.generate_access_token_totp(persist=True)\n"
    "  print('MINT', r)\n"
    "  print('STATUS', dhan.token_status())\n"
    "except Exception as e:\n"
    "  print('MINT_FAIL', type(e).__name__, e)\n"
    "PY'",
    timeout=90,
)

run(c, f"curl -s -H 'X-API-Key: {KEY}' http://127.0.0.1:8080/api/v1/desk/system/token")
run(c, f"tail -n 40 {CHROOT}{DESK}/logs/desk.out")
c.close()
