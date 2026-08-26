#!/usr/bin/env python3
"""Force VPS desk to paper+auto only (no mock fallback, live off).

  set EDGE_VPS_PASS=...
  python scripts/set_paper_auto_vps.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PORT = int(os.environ.get("EDGE_VPS_PORT", "443"))
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")
DESK = "/root/Options-Edge-Desk"
PY = "/root/Options-Edge-Lab/.venv/bin/python3"
LOCAL = Path(__file__).resolve().parents[1]

ENV_SET = {
    "DESK_MODE": "paper",
    "DESK_PAPER_AUTO": "1",
    "DESK_PAPER_ONLY": "1",
    "DESK_LIVE_ENABLED": "0",
    "LIVE_NIFTY": "0",
    "LIVE_BANKNIFTY": "0",
    "DESK_MOCK_LOOP": "0",
}


def run(c, cmd: str, timeout: int = 120, check: bool = True) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    if check and code != 0:
        raise RuntimeError(f"{code}: {cmd}\n{out}")
    return out


def main() -> int:
    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    # deploy schedule fix
    sftp = c.open_sftp()
    sftp.put(str(LOCAL / "app" / "schedule.py"), f"{DESK}/app/schedule.py")
    sftp.close()
    print("scp app/schedule.py", flush=True)

    merge = f"""
from pathlib import Path
desk = Path("{DESK}/.env")
bn = Path("/root/Options-Edge-Lab/.env")
vals = {{}}
if desk.exists():
    for line in desk.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
vals.update({json.dumps(ENV_SET)})
if bn.exists():
    for line in bn.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("DHAN_") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                vals[k.strip()] = v.strip()
desk.write_text("\\n".join(f"{{k}}={{v}}" for k, v in vals.items()) + "\\n", encoding="utf-8")
print("env updated", sorted(vals.keys()))
"""
    helper = f"{DESK}/scripts/_set_paper_env.py"
    sftp = c.open_sftp()
    with sftp.file(helper, "w") as fh:
        fh.write(merge)
    sftp.close()
    print(run(c, f"{PY} {helper}"), flush=True)

    # restart desk to reload .env
    run(c, "pkill -f 'uvicorn app.main:app' || true", timeout=15, check=False)
    run(
        c,
        f"cd {DESK} && nohup {PY} {DESK}/scripts/boot_desk.py "
        f">> {DESK}/logs/desk.out 2>&1 </dev/null & sleep 3; pgrep -af uvicorn | head -3",
        timeout=30,
    )
    print("desk restarted", flush=True)

    # read API key
    _, o, _ = c.exec_command(f"grep '^DESK_API_KEY=' {DESK}/.env | cut -d= -f2-", timeout=10)
    key = o.read().decode().strip()

    def api(method: str, path: str, body: dict | None = None) -> dict:
        if body is None:
            cmd = f"curl -s -X {method} -H 'X-API-Key: {key}' 'http://127.0.0.1:8080{path}'"
        else:
            cmd = (
                f"curl -s -X {method} -H 'X-API-Key: {key}' -H 'Content-Type: application/json' "
                f"-d '{json.dumps(body)}' 'http://127.0.0.1:8080{path}'"
            )
        _, o, _ = c.exec_command(cmd, timeout=45)
        raw = o.read().decode("utf-8", "replace")
        return json.loads(raw)

    # stop mock if running, arm paper+auto
    try:
        print("stop", api("POST", "/api/v1/desk/runner/stop", {"operator_id": "ops", "reason": "paper_only_cutover"}), flush=True)
    except Exception as exc:  # noqa: BLE001
        print("stop skip", exc, flush=True)

    start = api(
        "POST",
        "/api/v1/desk/runner/start",
        {"mode": "paper", "execution": "auto", "operator_id": "ops"},
    )
    print("start", json.dumps(start, indent=2), flush=True)

    status = api("GET", "/api/v1/desk/status")
    d = status.get("data") or status
    print(
        "STATUS",
        json.dumps(
            {k: d.get(k) for k in ("mode", "execution", "trading_active", "runner_state", "replay", "live_enabled", "market_session")},
            indent=2,
        ),
        flush=True,
    )
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
