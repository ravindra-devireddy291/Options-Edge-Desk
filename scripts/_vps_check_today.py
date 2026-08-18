"""One-shot VPS health check for why no trades today."""
from __future__ import annotations

import json
import os
from pathlib import Path

import paramiko


def load_env() -> None:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 40) -> str:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        out += "\n[stderr] " + err.strip()
    return out


def main() -> None:
    load_env()
    host = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
    pw = os.environ["EDGE_VPS_PASS"]
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username="root", password=pw, timeout=45, allow_agent=False, look_for_keys=False)

    checks = [
        ("trading_state", "chroot /mnt/sys cat /root/Options-Edge-Desk/data/trading_state.json 2>/dev/null || echo NO_STATE"),
        ("nifty_shadow_dir", "chroot /mnt/sys ls -la /root/Options-Nifty-Edge-Lab/reports/shadow/ 2>&1"),
        ("bn_shadow_dir", "chroot /mnt/sys ls -la /root/Options-Edge-Lab/reports/shadow/ 2>&1"),
        ("recent_shadows", "chroot /mnt/sys find /root/Options-Nifty-Edge-Lab/reports/shadow /root/Options-Edge-Lab/reports/shadow -name 'shadow_*.jsonl' 2>/dev/null | tail -15"),
        ("cron", "crontab -l 2>/dev/null || echo NO_CRON"),
        ("python_procs", "ps aux | grep python | grep -v grep | head -20"),
        ("desk_audit_tail", "chroot /mnt/sys tail -30 /root/Options-Edge-Desk/data/audit/events_2026-08-17.jsonl 2>/dev/null || echo NO_AUDIT"),
        ("auto_state", "chroot /mnt/sys cat /root/Options-Edge-Desk/data/auto_state.json 2>/dev/null || echo NO_AUTO_STATE"),
        ("orders_today", "chroot /mnt/sys ls -la /root/Options-Edge-Desk/data/orders/orders_2026-08-17.jsonl 2>/dev/null || echo NO_ORDERS"),
    ]
    for name, cmd in checks:
        print(f"\n{'='*60}\n{name}\n{'='*60}")
        print(run(c, cmd))

    live_py = r"""
import json, urllib.request
from pathlib import Path
key = next(
    (ln.split("=", 1)[1].strip().strip('"') for ln in Path("/root/Options-Edge-Desk/.env").read_text().splitlines() if ln.startswith("DESK_API_KEY=")),
    "",
)
for ep in ("/healthz", "/api/v1/desk/status", "/api/v1/desk/signals/today", "/api/v1/desk/snapshot"):
    req = urllib.request.Request("http://127.0.0.1:8080" + ep, headers={"X-API-Key": key})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read())
    if ep.endswith("snapshot"):
        slim = {"seq": d.get("seq")}
        if isinstance(d.get("status"), dict):
            s = d["status"]
            slim["status"] = {k: s.get(k) for k in (
                "mode", "execution", "trading_active", "runner_state", "market_session",
                "token_ok", "broker_reachable", "shadow_book_halted", "available_cash",
                "open_positions", "last_error",
            )}
        sig = d.get("signals") or {}
        slim["signals"] = {
            "count": sig.get("count"),
            "pending": sum(1 for x in (sig.get("signals") or []) if str(x.get("status", "")).upper() == "PENDING"),
        }
        d = slim
    print("=== LIVE", ep, "===")
    print(json.dumps(d, indent=2)[:2400])
"""
    print(f"\n{'='*60}\nlive_api\n{'='*60}")
    print(run(c, f"chroot /mnt/sys bash -lc '/root/Options-Edge-Lab/.venv/bin/python3 -c {json.dumps(live_py)}'", timeout=120))

    print(f"\n{'='*60}\ndebug_script\n{'='*60}")
    print(
        run(
            c,
            "chroot /mnt/sys bash -lc 'cd /root/Options-Edge-Desk && /root/Options-Edge-Lab/.venv/bin/python3 scripts/_debug_no_trades.py 2>&1'",
            timeout=90,
        )
    )
    c.close()


if __name__ == "__main__":
    main()
