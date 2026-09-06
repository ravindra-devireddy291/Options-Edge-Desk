#!/usr/bin/env python3
"""Black-box Monday paper: close ops holes on the VPS. No Dhan buy/sell. No secret prints."""
from __future__ import annotations

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
REMOTE = "/root/Options-Edge-Desk"
PY = "/root/Options-Edge-Lab/.venv/bin/python3"
ROOT = Path(__file__).resolve().parents[1]
NIFTY_LOCAL = Path(r"D:\Options-Nifty-Edge-Lab")
BN_LOCAL = Path(r"D:\Options-Edge-Lab")

INNER = r'''
import json
from pathlib import Path

desk = Path("/root/Options-Edge-Desk")
envp = desk / ".env"
vals = {}
if envp.exists():
    for ln in envp.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            vals[k.strip()] = v.strip()
bn = Path("/root/Options-Edge-Lab/.env")
if bn.exists():
    for ln in bn.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            k, v = k.strip(), v.strip()
            if k in ("DHAN_PIN", "DHAN_TOTP_SECRET", "DHAN_CLIENT_ID") and v and not vals.get(k):
                vals[k] = v
want = {
    "DESK_MODE": "paper",
    "DESK_PAPER_AUTO": "1",
    "DESK_PAPER_ONLY": "1",
    "DESK_LIVE_ENABLED": "0",
    "LIVE_NIFTY": "0",
    "LIVE_BANKNIFTY": "0",
    "DESK_MOCK_LOOP": "0",
    "NIFTY_CONFIG": "config/rungs/nifty_alpha.yaml",
    "BN_CONFIG": "config/rungs/bn_alpha.yaml",
    "NIFTY_LAB_ROOT": "/root/Options-Nifty-Edge-Lab",
    "BN_LAB_ROOT": "/root/Options-Edge-Lab",
}
changed = []
for k, v in want.items():
    if vals.get(k) != v:
        vals[k] = v
        changed.append(k)
envp.write_text("\n".join(f"{k}={v}" for k, v in vals.items()) + "\n", encoding="utf-8")
print("ENV_PATCH", ",".join(changed) or "none")
print("BFF_SET", bool(vals.get("DESK_BFF_SECRET")))
print("API_KEY_SET", bool(vals.get("DESK_API_KEY")))
print("TOTP_SET", bool(vals.get("DHAN_TOTP_SECRET")))
print("PIN_SET", bool(vals.get("DHAN_PIN")))

st = desk / "data" / "trading_state.json"
raw = json.loads(st.read_text(encoding="utf-8")) if st.exists() else {}
kill_was = bool(raw.get("kill_active"))
raw["kill_active"] = False
raw["kill_reason"] = None
raw["mode"] = "paper"
st.parent.mkdir(parents=True, exist_ok=True)
st.write_text(json.dumps(raw, indent=2), encoding="utf-8")
print("KILL_WAS", kill_was)
print("KILL_CLEARED", True)
print("MODE_PAPER", True)

nroot = Path(vals["NIFTY_LAB_ROOT"])
broot = Path(vals["BN_LAB_ROOT"])
for rel in ("config/rungs/nifty_alpha.yaml", "config/rungs/nifty_stable.yaml"):
    print("YAML", rel, (nroot / rel).is_file())
for rel in ("config/rungs/bn_alpha.yaml", "config/rungs/bn_stable.yaml"):
    print("YAML", rel, (broot / rel).is_file())
print("NIFTY_DAILY", (nroot / "scripts" / "run_shadow_daily.py").is_file())
print("BN_DAILY", (broot / "scripts" / "run_shadow_daily.py").is_file())
print("DESK_BOOKS_FN", "def desk_books" in (desk / "app" / "books" / "adapters.py").read_text(encoding="utf-8"))
'''

WARM = r'''
import os
os.chdir("/root/Options-Edge-Desk")
from app.brokers.dhan import client as dhan
from app.brokers.dhan.contracts import option_rows
dhan.load_dotenv()
try:
    tok = dhan.ensure_fresh_token()
    print("TOKEN_ACTION", tok.get("action") or tok.get("ok"))
except Exception as e:
    print("TOKEN_ERR", type(e).__name__, str(e)[:160])
view = dhan.token_public_view()
print("TOKEN_OK", view.get("token_ok"), "LEFT", view.get("seconds_left"))
try:
    n = len(option_rows("NIFTY"))
    b = len(option_rows("BANKNIFTY"))
    print("SCRIP", n, b)
except Exception as e:
    print("SCRIP_ERR", type(e).__name__, str(e)[:160])
try:
    spots = dhan.spots_with_change()
    print("SPOT_N", (spots.get("NIFTY") or {}).get("ltp") is not None, "SPOT_BN", (spots.get("BANKNIFTY") or {}).get("ltp") is not None)
except Exception as e:
    print("SPOT_ERR", type(e).__name__, str(e)[:160])
from app.runners.state import RUNNER
RUNNER.mode = "paper"
from app.books.adapters import desk_books
packs = desk_books()
print("PACKS", len(packs), [p.pack_id for p in packs])
'''

STATUS = r'''
import json
import urllib.request
from pathlib import Path
vals = {}
for ln in Path("/root/Options-Edge-Desk/.env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1)
        vals[k.strip()] = v.strip()
h = {"X-API-Key": vals.get("DESK_API_KEY", "")}
if vals.get("DESK_BFF_SECRET"):
    h["X-Desk-BFF"] = vals["DESK_BFF_SECRET"]
req = urllib.request.Request("http://127.0.0.1:8080/api/v1/desk/status", headers=h)
with urllib.request.urlopen(req, timeout=25) as r:
    d = json.loads(r.read()).get("data") or {}
keys = (
    "mode", "execution", "trading_active", "runner_state", "token_ok",
    "broker_reachable", "live_enabled", "paper_auto", "kill_switch_active", "last_error",
)
print({k: d.get(k) for k in keys})
print("BOOKS", [b.get("label") for b in (d.get("books") or [])])
cut = ((d.get("live_cutover") or {}).get("books") or [])
print("CUTOVER", [(b.get("label") or b.get("underlying"), b.get("oms"), b.get("uses_dhan")) for b in cut])
'''


def run(c, cmd: str, timeout: int = 60) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    return out.strip()


def _put(sftp, local: Path, remote: str) -> None:
    if not local.exists():
        print("missing local", local, flush=True)
        return
    sftp.put(str(local), remote)
    print("scp", local.name, "->", remote, flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pw = os.environ.get("EDGE_VPS_PASS", "")
    if not pw:
        raise SystemExit("Set EDGE_VPS_PASS")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=pw, timeout=60, allow_agent=False, look_for_keys=False)

    run(
        c,
        "mkdir -p /root/Options-Nifty-Edge-Lab/config/rungs /root/Options-Nifty-Edge-Lab/scripts "
        "/root/Options-Edge-Lab/config/rungs /root/Options-Edge-Lab/scripts "
        "/root/Options-Edge-Desk/scripts /root/Options-Edge-Desk/data",
        timeout=20,
    )
    sftp = c.open_sftp()
    for rel, dest in (
        ("config/rungs/nifty_alpha.yaml", "/root/Options-Nifty-Edge-Lab/config/rungs/nifty_alpha.yaml"),
        ("config/rungs/nifty_stable.yaml", "/root/Options-Nifty-Edge-Lab/config/rungs/nifty_stable.yaml"),
        ("scripts/run_shadow_daily.py", "/root/Options-Nifty-Edge-Lab/scripts/run_shadow_daily.py"),
        ("scripts/run_shadow_journal.py", "/root/Options-Nifty-Edge-Lab/scripts/run_shadow_journal.py"),
    ):
        _put(sftp, NIFTY_LOCAL / rel, dest)
    for rel, dest in (
        ("config/rungs/bn_alpha.yaml", "/root/Options-Edge-Lab/config/rungs/bn_alpha.yaml"),
        ("config/rungs/bn_stable.yaml", "/root/Options-Edge-Lab/config/rungs/bn_stable.yaml"),
        ("scripts/run_shadow_daily.py", "/root/Options-Edge-Lab/scripts/run_shadow_daily.py"),
        ("scripts/run_shadow_journal.py", "/root/Options-Edge-Lab/scripts/run_shadow_journal.py"),
    ):
        _put(sftp, BN_LOCAL / rel, dest)
    for rel, remote in (
        ("deploy/desk-watchdog.sh", "/usr/local/bin/desk-watchdog.sh"),
        ("deploy/desk-watchdog.service", "/etc/systemd/system/desk-watchdog.service"),
        ("deploy/desk-watchdog.timer", "/etc/systemd/system/desk-watchdog.timer"),
        ("deploy/edge-desk.service", "/etc/systemd/system/edge-desk.service"),
        ("deploy/cloudflared.service", "/etc/systemd/system/cloudflared.service"),
    ):
        local = ROOT / rel
        if local.exists():
            data = local.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            with sftp.file(remote, "wb") as fh:
                fh.write(data)
            print("scp", rel, "->", remote, flush=True)
    try:
        sftp.chmod("/usr/local/bin/desk-watchdog.sh", 0o755)
    except Exception:
        pass
    for name, body in (
        ("_monday_patch.py", INNER),
        ("_monday_warm.py", WARM),
        ("_monday_status.py", STATUS),
    ):
        with sftp.file(f"{REMOTE}/scripts/{name}", "w") as fh:
            fh.write(body)
    sftp.close()

    print("=== PATCH ===", flush=True)
    print(run(c, f"{PY} {REMOTE}/scripts/_monday_patch.py", timeout=30), flush=True)

    print("=== UNITS ===", flush=True)
    print(
        run(
            c,
            "systemctl daemon-reload; "
            "systemctl enable --now desk-watchdog.timer edge-desk; "
            "systemctl enable cloudflared; "
            "systemctl is-active --quiet cloudflared || systemctl start cloudflared; "
            "echo EDGE $(systemctl is-active edge-desk); "
            "echo CF $(systemctl is-active cloudflared); "
            "echo WD $(systemctl is-active desk-watchdog.timer)",
            timeout=45,
        ),
        flush=True,
    )

    print("=== RESTART ===", flush=True)
    print(
        run(
            c,
            "systemctl stop edge-desk; "
            "fuser -k 8080/tcp >/dev/null 2>&1 || true; "
            "sleep 2; "
            "systemctl start edge-desk; "
            "sleep 6; "
            "echo EDGE $(systemctl is-active edge-desk); "
            "echo MAINPID $(systemctl show -p MainPID --value edge-desk); "
            "ss -ltnp | grep 8080 || true; "
            "curl -s --max-time 8 http://127.0.0.1:8080/healthz",
            timeout=45,
        ),
        flush=True,
    )

    print("=== WARM ===", flush=True)
    print(
        run(
            c,
            f"cd {REMOTE} && PYTHONPATH={REMOTE} {PY} {REMOTE}/scripts/_monday_warm.py",
            timeout=120,
        ),
        flush=True,
    )

    print("=== STATUS ===", flush=True)
    print(run(c, f"{PY} {REMOTE}/scripts/_monday_status.py", timeout=40), flush=True)

    print("=== PUBLIC ===", flush=True)
    print(
        run(
            c,
            "curl -sS -o /dev/null -w 'deskapi %{http_code}\\n' --max-time 12 https://deskapi.ravindra-devireddy.com/healthz; "
            "curl -sS -o /dev/null -w 'ui %{http_code}\\n' --max-time 12 https://desk.ravindra-devireddy.com/",
            timeout=30,
        ),
        flush=True,
    )
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
