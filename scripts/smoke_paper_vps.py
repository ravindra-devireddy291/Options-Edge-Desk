#!/usr/bin/env python3
import json
import os
import urllib.request

import paramiko

KEY = os.environ.get("DESK_API_KEY", "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c=")
HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]

body = json.dumps(
    {
        "underlying": "NIFTY",
        "sleeve": "fade",
        "security_id": "0",
        "side": "BUY",
        "quantity": 1,
        "symbol": "NIFTY-FADE",
        "tag": "simulate",
        "dry_run": True,
    }
)
# run curl on VPS to avoid local tunnel
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)
# write body to temp file to avoid quoting hell
sftp = c.open_sftp()
with sftp.file("/tmp/paper.json", "w") as fh:
    fh.write(body)
sftp.close()
cmd = (
    f"curl -s -H 'X-API-Key: {KEY}' -H 'Content-Type: application/json' "
    f"--data @/tmp/paper.json http://127.0.0.1:8080/api/v1/desk/orders/paper"
)
_, o, e = c.exec_command(cmd, timeout=60)
print(o.read().decode())
print(e.read().decode())
c.close()
