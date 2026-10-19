#!/usr/bin/env python3
import json
import os
from pathlib import Path

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

KEY = _require_desk_api_key()
PASS = os.environ["EDGE_VPS_PASS"]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("87.232.72.137", username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)


def sh(cmd: str) -> str:
    _, o, e = c.exec_command(cmd, timeout=60)
    return o.read().decode() + e.read().decode()


sftp = c.open_sftp()
with sftp.file("/tmp/start.json", "w") as fh:
    fh.write(json.dumps({"mode": "paper", "operator_id": "ops"}))
with sftp.file("/tmp/stop.json", "w") as fh:
    fh.write(json.dumps({"operator_id": "ops", "reason": "verify trading-only stop"}))
sftp.close()

print("HEALTH0", sh("curl -s http://127.0.0.1:8080/healthz"))
print(
    "START",
    sh(
        f"curl -s -H 'X-API-Key: {KEY}' -H 'Content-Type: application/json' "
        f"--data @/tmp/start.json http://127.0.0.1:8080/api/v1/desk/runner/start"
    ),
)
print("HEALTH1", sh("curl -s http://127.0.0.1:8080/healthz"))
print(
    "STOP",
    sh(
        f"curl -s -H 'X-API-Key: {KEY}' -H 'Content-Type: application/json' "
        f"--data @/tmp/stop.json http://127.0.0.1:8080/api/v1/desk/runner/stop"
    ),
)
print("HEALTH2", sh("curl -s http://127.0.0.1:8080/healthz"))
print(
    "TOKEN",
    sh(f"curl -s -H 'X-API-Key: {KEY}' http://127.0.0.1:8080/api/v1/desk/system/token")[:500],
)
c.close()
