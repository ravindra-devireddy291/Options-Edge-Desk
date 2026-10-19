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

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "87.232.72.137",
    username="root",
    password=os.environ["EDGE_VPS_PASS"],
    timeout=60,
    allow_agent=False,
    look_for_keys=False,
)
key = _require_desk_api_key()
_, o, _ = c.exec_command(
    "curl -s http://127.0.0.1:8080/healthz; echo; "
    f"curl -s -H 'X-API-Key: {key}' http://127.0.0.1:8080/api/v1/desk/system/token; echo; "
    "tail -n 15 /mnt/sys/root/Options-Edge-Desk/logs/desk.out"
)
print(o.read().decode())
c.close()
