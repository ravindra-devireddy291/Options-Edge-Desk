#!/usr/bin/env python3
"""Confirm VPS token env + desk token_ok after TOTP mint."""
from __future__ import annotations

import os
import time

import paramiko

def _require_desk_api_key() -> str:
    key = (os.environ.get("DESK_API_KEY") or "").strip()
    if not key:
        from pathlib import Path
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("DESK_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        raise SystemExit("Set DESK_API_KEY")
    return key

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]
KEY = _require_desk_api_key()
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"


def run(c, cmd: str, timeout: int = 90) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    print(out, flush=True)
    return out


c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

run(
    c,
    f"chroot {CHROOT} python3 - <<'PY'\n"
    "from pathlib import Path\n"
    f"vals={{}}\n"
    f"for line in Path('{DESK}/.env').read_text().splitlines():\n"
    "  if '=' in line and not line.strip().startswith('#'):\n"
    "    k,v=line.split('=',1); vals[k.strip()]=v.strip()\n"
    "for k in ['DHAN_CLIENT_ID','DHAN_PIN','DHAN_TOTP_SECRET','DHAN_ACCESS_TOKEN']:\n"
    "  v=vals.get(k,'')\n"
    "  print(k, 'SET' if v else 'EMPTY', 'len', len(v))\n"
    "PY",
)

# restart loading env with python export to avoid bash JWT issues
run(c, "mountpoint -q /mnt/sys/proc || mount -t proc proc /mnt/sys/proc")
run(c, "fuser -k 8080/tcp 2>/dev/null || true; sleep 1")
run(
    c,
    f"nohup chroot {CHROOT} /bin/bash -c "
    f"'cd {DESK} && "
    f"/root/Options-Edge-Lab/.venv/bin/python3 - <<\"PY\"\n"
    "import os, subprocess\n"
    "from pathlib import Path\n"
    f"env={{}}\n"
    "for line in Path('.env').read_text().splitlines():\n"
    "    line=line.strip()\n"
    "    if not line or line.startswith('#') or \"=\" not in line: continue\n"
    "    k,v=line.split(\"=\",1)\n"
    "    env[k.strip()]=v.strip()\n"
    "os.environ.update(env)\n"
    "os.environ[\"PYTHONPATH\"]=\"" + DESK + "\"\n"
    "print(\"boot token_len\", len(os.environ.get(\"DHAN_ACCESS_TOKEN\",\"\")), \"totp\", bool(os.environ.get(\"DHAN_TOTP_SECRET\")))\n"
    "subprocess.Popen([\n"
    "  \"/root/Options-Edge-Lab/.venv/bin/python3\",\"-m\",\"uvicorn\",\"app.main:app\",\n"
    "  \"--host\",\"127.0.0.1\",\"--port\",\"8080\"\n"
    "], env=os.environ, cwd=\"" + DESK + "\",\n"
    f"  stdout=open(\"{DESK}/logs/desk.out\",\"a\"), stderr=subprocess.STDOUT)\n"
    "PY' "
    f"> /tmp/desk_boot.log 2>&1; sleep 4; cat /tmp/desk_boot.log; "
    f"curl -s http://127.0.0.1:8080/healthz; echo; "
    f"curl -s -H 'X-API-Key: {KEY}' http://127.0.0.1:8080/api/v1/desk/system/token; echo",
    timeout=60,
)
c.close()
