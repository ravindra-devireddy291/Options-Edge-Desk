"""Debug why paper-auto has zero trades today."""
from __future__ import annotations

import json
import os
from pathlib import Path

import paramiko

desk_env = Path(__file__).resolve().parents[1] / ".env"
if desk_env.exists():
    for line in desk_env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]

DEBUG_PY = r'''
import json
import os
from pathlib import Path
from datetime import date

# load desk .env
desk = Path("/root/Options-Edge-Desk")
for line in (desk / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import sys
sys.path.insert(0, str(desk))

from app.session import session_day, now_ist, market_session
from app.runners.state import RUNNER
from app.schedule import env_paper_auto, in_cash_window, paused_today, schedule_wanted
from app.books import adapters as books
from app.auth import get_settings

day = session_day().isoformat()
now = now_ist()
print("=== TIME ===")
print("now", now.isoformat(), "weekday", now.weekday(), "session", market_session(), "day", day)
print("in_cash_window", in_cash_window(), "paused_today", paused_today(), "schedule_wanted", schedule_wanted())
print("env_paper_auto", env_paper_auto())
print("=== RUNNER ===")
print("mode", RUNNER.mode, "execution", RUNNER.execution, "state", RUNNER.state, "trading_active", RUNNER.trading_active())
print("paused_day", RUNNER.paused_day, "kill", RUNNER.kill.active, "paper_auto_schedule", RUNNER.paper_auto_schedule)
print("last_error", (RUNNER.last_error or "")[:200])

s = get_settings()
nifty_root = Path(s.nifty_lab_root)
bn_root = Path(s.bn_lab_root)
print("=== LAB PATHS ===")
print("nifty_root", nifty_root, "exists", nifty_root.exists())
print("bn_root", bn_root, "exists", bn_root.exists())
print("nifty_config", s.nifty_config, "exists", (nifty_root / s.nifty_config).exists())
print("bn_config", s.bn_config, "exists", (bn_root / s.bn_config).exists())

book_list = [
    books.nifty_book(s.nifty_lab_root, s.nifty_config),
    books.bn_book(s.bn_lab_root, s.bn_config),
]
for b in book_list:
    sh = b.shadow_dir
    j = sh / f"shadow_{day}.jsonl"
    print(f"=== {b.name} shadow ===")
    print("shadow_dir", sh, "exists", sh.exists())
    print("today_journal", j, "exists", j.exists(), "bytes", j.stat().st_size if j.exists() else 0)
    if j.exists():
        rows = []
        for line in j.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        print("rows_today", len(rows))
        statuses = {}
        for r in rows:
            lab = r.get("lab") or {}
            st = str(lab.get("status") or r.get("status") or "?")
            statuses[st] = statuses.get(st, 0) + 1
        print("status_counts", statuses)
        for r in rows[-3:]:
            lab = r.get("lab") or {}
            print("sample", json.dumps({
                "sleeve": r.get("sleeve"),
                "status": lab.get("status"),
                "symbol": lab.get("symbol"),
                "day": lab.get("day"),
                "signal_id": r.get("signal_id") or lab.get("signal_id"),
            }, default=str)[:200])
    else:
        # list recent journals
        recent = sorted(sh.glob("shadow_*.jsonl"))[-5:] if sh.exists() else []
        print("recent_journals", [p.name for p in recent])

shadow = books.shadow_book_status(book_list)
print("=== SHADOW BOOK ===")
print(json.dumps(shadow, default=str)[:500])

compass = books.signals_today(book_list, day)
print("=== COMPASS (signals_today) ===")
print("count", compass.get("count"), "pending", sum(1 for x in (compass.get("signals") or []) if str(x.get("status","")).upper()=="PENDING"))
for sig in (compass.get("signals") or [])[:5]:
    print("signal", json.dumps({k: sig.get(k) for k in ("signal_id","underlying","status","sleeve","symbol","action")}, default=str))

trades = books.trades_today(book_list, day)
print("=== TRADES TODAY ===")
print("trade_count", trades.get("trade_count"), "closed", trades.get("closed_count"))

# auto engine state
auto_path = desk / "data" / "auto_state.json"
print("=== AUTO STATE ===")
if auto_path.exists():
    print(auto_path.read_text()[:400])
else:
    print("no auto_state.json")

# audit today
audit_dir = desk / "data" / "audit"
print("=== AUDIT (auto/order today) ===")
for pat in [f"events_{day}.jsonl", f"orders_{day}.jsonl"]:
    p = audit_dir / pat
    if not p.exists():
        # also try files matching
        matches = list(audit_dir.glob(f"*{day}*"))
        print(pat, "missing", "matches", [m.name for m in matches])
        continue
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    print(pat, "lines", len(lines))
    for ln in lines:
        if any(k in ln for k in ("auto.", "order.", "schedule", "shadow", "trading.")):
            print(" ", ln[:220])

# check if lab processes/cron exist
print("=== LAB PROCESSES (grep) ===")
import subprocess
for pat in ["nifty", "edge", "shadow", "compass", "cron"]:
    pass
'''

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

remote = "/mnt/sys/root/Options-Edge-Desk/scripts/_debug_no_trades.py"
sftp = c.open_sftp()
with sftp.file(remote, "w") as f:
    f.write(DEBUG_PY)
sftp.close()

_, o, e = c.exec_command(
    "chroot /mnt/sys bash -lc 'cd /root/Options-Edge-Desk && /root/Options-Edge-Lab/.venv/bin/python3 scripts/_debug_no_trades.py'",
    timeout=120,
)
out = o.read().decode("utf-8", "replace")
err = e.read().decode("utf-8", "replace")
print(out)
if err.strip():
    print("STDERR", err[:800])
c.close()
