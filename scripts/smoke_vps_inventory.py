"""SSH to VPS and hit every trader route on 127.0.0.1:8080. Never prints secrets."""
from __future__ import annotations

import json
import os
import sys

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ.get("EDGE_VPS_PASS", "")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"
PY = "/root/Options-Edge-Lab/.venv/bin/python3"

REMOTE_PY = r'''
import json, urllib.error, urllib.request
from pathlib import Path

vals = {}
for line in Path("/root/Options-Edge-Desk/.env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    vals[k.strip()] = v.strip().strip('"').strip("'")
KEY = vals.get("DESK_API_KEY") or ""
BASE = "http://127.0.0.1:8080"
rows = []

def call(method, path, body=None, auth=True):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if auth:
        headers["X-API-Key"] = KEY
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw

def rec(name, status, payload):
    ok = False
    detail = ""
    if isinstance(payload, dict):
        ok = bool(payload.get("ok") is True or payload.get("desk_process") == "alive" or payload.get("service"))
        data = payload.get("data") if "data" in payload else payload
        if isinstance(data, dict) and "accepted" in data:
            detail = "accepted=%s code=%s" % (data.get("accepted"), data.get("code"))
        elif isinstance(data, dict) and "active" in data:
            trig = data.get("trigger") or {}
            detail = "active=%s role=%s" % (data.get("active"), trig.get("role"))
        elif isinstance(data, dict) and "mode" in data:
            detail = "mode=%s exec=%s trading=%s" % (data.get("mode"), data.get("execution"), data.get("trading_active"))
        elif isinstance(data, dict) and "row_count" in data:
            detail = "rows=%s" % data.get("row_count")
        elif isinstance(data, dict) and "count" in data:
            detail = "count=%s" % data.get("count")
        elif isinstance(data, dict) and "NIFTY" in data:
            detail = "spots"
        else:
            detail = str(list(data.keys())[:6] if isinstance(data, dict) else type(data).__name__)
    else:
        detail = str(payload)[:120]
    mark = "PASS" if status == 200 and ok else "FAIL"
    if name.startswith("401 ") :
        mark = "PASS" if status == 401 else "FAIL"
    rows.append((mark, name, status, detail))
    print("%s %s %s %s" % (mark, status, name, detail), flush=True)

rec("GET /healthz", *call("GET", "/healthz", auth=False))
rec("401 GET /status no key", *call("GET", "/api/v1/desk/status", auth=False))
rec("GET /status", *call("GET", "/api/v1/desk/status"))
rec("GET /positions", *call("GET", "/api/v1/desk/positions"))
rec("GET /orders/open", *call("GET", "/api/v1/desk/orders/open"))
rec("GET /trades/today", *call("GET", "/api/v1/desk/trades/today"))
rec("GET /signals/today", *call("GET", "/api/v1/desk/signals/today"))
rec("GET /research/stable", *call("GET", "/api/v1/desk/research/stable"))
rec("GET /research/stable/NIFTY", *call("GET", "/api/v1/desk/research/stable/NIFTY"))
rec("GET /research/stable/BANKNIFTY", *call("GET", "/api/v1/desk/research/stable/BANKNIFTY"))
rec("GET /contracts NIFTY", *call("GET", "/api/v1/desk/contracts?underlying=NIFTY"))
rec("GET /quotes/spot", *call("GET", "/api/v1/desk/quotes/spot"))
rec("GET /quotes/option", *call("GET", "/api/v1/desk/quotes/option?underlying=NIFTY&option_type=PE&strike=24000&expiry=2026-06-25"))
rec("GET /gates NIFTY", *call("GET", "/api/v1/desk/gates?underlying=NIFTY"))
rec("GET /triggers/active", *call("GET", "/api/v1/desk/triggers/active"))
rec("POST /triggers/ack", *call("POST", "/api/v1/desk/triggers/ack", {"trigger_id": "smoke-none", "action": "dismiss"}))
rec("POST /sync", *call("POST", "/api/v1/desk/sync", {}))
paper_body = {
    "underlying": "NIFTY", "sleeve": "fade", "side": "BUY", "lots": 1, "symbol": "",
    "strike": 24000, "option_type": "PE", "expiry": "2026-06-25", "dry_run": True, "operator_id": "ui",
}
rec("POST /orders/paper dry_run", *call("POST", "/api/v1/desk/orders/paper", paper_body))
rec("POST /orders/cancel missing", *call("POST", "/api/v1/desk/orders/cancel", {"order_id": "no-such-order", "operator_id": "ui"}))
rec("POST /runner/start mock manual", *call("POST", "/api/v1/desk/runner/start", {"mode": "mock", "execution": "manual", "operator_id": "ui", "speed": 60}))
rec("GET /status mock", *call("GET", "/api/v1/desk/status"))
rec("GET /positions mock", *call("GET", "/api/v1/desk/positions"))
rec("GET /orders/open mock", *call("GET", "/api/v1/desk/orders/open"))
rec("GET /trades/today mock", *call("GET", "/api/v1/desk/trades/today"))
rec("GET /signals/today mock", *call("GET", "/api/v1/desk/signals/today"))
rec("GET /contracts mock", *call("GET", "/api/v1/desk/contracts?underlying=NIFTY"))
rec("GET /quotes/spot mock", *call("GET", "/api/v1/desk/quotes/spot"))
rec("GET /quotes/option mock", *call("GET", "/api/v1/desk/quotes/option?underlying=NIFTY&option_type=PE"))
rec("GET /gates mock", *call("GET", "/api/v1/desk/gates?underlying=NIFTY"))
rec("GET /triggers mock manual", *call("GET", "/api/v1/desk/triggers/active"))
rec("POST /sync mock", *call("POST", "/api/v1/desk/sync", {}))
rec("POST /orders/paper mock dry_run", *call("POST", "/api/v1/desk/orders/paper", paper_body))
rec("POST /runner/start mock auto", *call("POST", "/api/v1/desk/runner/start", {"mode": "mock", "execution": "auto", "operator_id": "ui", "speed": 600}))
rec("GET /status mock auto", *call("GET", "/api/v1/desk/status"))
rec("GET /triggers mock auto", *call("GET", "/api/v1/desk/triggers/active"))
rec("GET /positions mock auto", *call("GET", "/api/v1/desk/positions"))
rec("POST /runner/stop", *call("POST", "/api/v1/desk/runner/stop", {"operator_id": "ui", "reason": "smoke"}))
rec("POST /runner/start paper manual", *call("POST", "/api/v1/desk/runner/start", {"mode": "paper", "execution": "manual", "operator_id": "ui"}))
rec("GET /status paper", *call("GET", "/api/v1/desk/status"))
rec("GET /triggers paper", *call("GET", "/api/v1/desk/triggers/active"))
rec("POST /sync paper", *call("POST", "/api/v1/desk/sync", {}))
rec("POST /runner/stop paper", *call("POST", "/api/v1/desk/runner/stop", {"operator_id": "ui", "reason": "smoke"}))
rec("POST /runner/start live manual", *call("POST", "/api/v1/desk/runner/start", {"mode": "live", "execution": "manual", "operator_id": "ui"}))
rec("GET /status live", *call("GET", "/api/v1/desk/status"))
rec("POST /runner/stop live", *call("POST", "/api/v1/desk/runner/stop", {"operator_id": "ui", "reason": "smoke"}))
rec("POST /runner/start paper auto", *call("POST", "/api/v1/desk/runner/start", {"mode": "paper", "execution": "auto", "operator_id": "ui"}))
rec("GET /triggers paper auto", *call("GET", "/api/v1/desk/triggers/active"))
rec("POST /runner/stop paper auto", *call("POST", "/api/v1/desk/runner/stop", {"operator_id": "ui", "reason": "smoke-no-autofill"}))
fails = [r for r in rows if r[0] != "PASS"]
print()
print("%s/%s PASS, %s FAIL" % (len(rows) - len(fails), len(rows), len(fails)))
raise SystemExit(1 if fails else 0)
'''


def main() -> int:
    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)
    remote = f"{CHROOT}{DESK}/scripts/_smoke_vps_inventory.py"
    sftp = c.open_sftp()
    with sftp.file(remote, "w") as fh:
        fh.write(REMOTE_PY)
    sftp.close()
    cmd = f"chroot {CHROOT} bash -lc '{PY} {DESK}/scripts/_smoke_vps_inventory.py'"
    _, o, e = c.exec_command(cmd, timeout=180)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    c.close()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
