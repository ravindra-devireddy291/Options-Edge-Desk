"""Deep forensics: why paper registered zero trades. No secrets printed."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"

INNER = r"""
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
import os

IST_DAY = date(2026, 8, 17)
DESK = Path("/root/Options-Edge-Desk")
NIFTY = Path("/root/Options-Nifty-Edge-Lab")
BN = Path("/root/Options-Edge-Lab")

def load_env():
    for ln in (DESK / ".env").read_text().splitlines():
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def jload(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        return {"_error": str(e)[:200]}

def jsonl(path, limit=None):
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            rows.append({"_raw": ln[:180]})
        if limit and len(rows) >= limit:
            break
    return rows

def kinds(rows):
    c = Counter(str(r.get("kind") or r.get("event") or "?") for r in rows)
    return dict(c)

print("==== 1. CLOCK / RUNNER ====")
load_env()
import sys
sys.path.insert(0, str(DESK))
from app.session import now_ist, market_session, session_day
from app.runners.state import RUNNER
from app.schedule import in_cash_window, paused_today, schedule_wanted, env_paper_auto
now = now_ist()
print("now_ist", now.isoformat(), "weekday", now.weekday(), "session", market_session())
print("session_day", session_day().isoformat(), "target", IST_DAY.isoformat())
print("in_cash", in_cash_window(), "paused", paused_today(), "schedule_wanted", schedule_wanted(), "paper_auto_env", env_paper_auto())
print("runner", json.dumps({
    "mode": RUNNER.mode, "execution": RUNNER.execution, "state": RUNNER.state,
    "trading_active": RUNNER.trading_active(), "paused_day": RUNNER.paused_day,
    "kill": RUNNER.kill.active, "paper_auto_schedule": RUNNER.paper_auto_schedule,
    "last_error": (RUNNER.last_error or "")[:180],
}, default=str))
print("trading_state_file", json.dumps(jload(DESK / "data/trading_state.json"), default=str)[:800])

print("\n==== 2. PAPER ARCHIVES ====")
paper = DESK / "data/paper"
if paper.exists():
    for p in sorted(paper.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(p.name, "UNREADABLE", e)
            continue
        print(p.name, json.dumps({
            "saved_at": d.get("saved_at") or d.get("at"),
            "reason": d.get("reason"),
            "mode": d.get("mode"),
            "trade_count": d.get("trade_count") or len(d.get("trades") or []),
            "signal_count": d.get("signal_count") or len(d.get("signals") or []),
            "keys": sorted(list(d.keys()))[:20],
        }, default=str))
else:
    print("NO paper dir")

print("\n==== 3. AUDIT 2026-08-17 (kinds + schedule/lab/auto/order) ====")
audit = DESK / "data/audit"
day = IST_DAY.isoformat()
events = jsonl(audit / f"events_{day}.jsonl")
print("events_lines", len(events), "kinds", kinds(events))
interesting = ("schedule", "lab.", "auto.", "order.", "trading.", "kill", "shadow")
for r in events:
    k = str(r.get("kind") or "")
    if any(x in k for x in interesting):
        slim = {x: r.get(x) for x in ("ts", "kind", "reason", "mode", "ok", "nifty", "bn", "signal_id", "code", "accepted", "underlying") if x in r or True}
        slim = {x: r.get(x) for x in ("ts", "kind", "reason", "mode", "ok", "nifty", "bn", "signal_id", "code", "accepted", "underlying", "operator_id")}
        print(" ", json.dumps({k2: v for k2, v in slim.items() if v is not None}, default=str)[:240])
orders = jsonl(audit / f"orders_{day}.jsonl")
print("orders_lines", len(orders))
for r in orders[:8]:
    print("  order", json.dumps({k: r.get(k) for k in ("ts", "state", "underlying", "side", "mode", "client_order_id")}, default=str)[:220])

print("\n==== 4. AUTO STATE ====")
print((DESK / "data/auto_state.json").read_text()[:400] if (DESK / "data/auto_state.json").exists() else "missing")

print("\n==== 5. SHADOW JOURNALS ====")
for root, name in ((NIFTY, "NIFTY"), (BN, "BANKNIFTY")):
    sh = root / "reports/shadow"
    files = sorted(sh.glob("shadow_*.jsonl")) if sh.exists() else []
    print(name, "dir", sh, "exists", sh.exists(), "n_files", len(files))
    print("  files", [f.name for f in files[-12:]])
    today = sh / f"shadow_{day}.jsonl"
    print("  today_exists", today.exists(), "bytes", today.stat().st_size if today.exists() else 0)
    if today.exists():
        rows = jsonl(today)
        st = Counter(str((r.get("lab") or {}).get("status") or r.get("status") or "?") for r in rows)
        sl = Counter(str(r.get("sleeve") or "?") for r in rows)
        tr = Counter(str(bool(r.get("tradeable"))) for r in rows)
        print("  rows", len(rows), "lab_status", dict(st), "sleeves", dict(sl), "tradeable", dict(tr))
        for r in rows:
            lab = r.get("lab") or {}
            print("  row", json.dumps({
                "sleeve": r.get("sleeve"),
                "tradeable": r.get("tradeable"),
                "status": lab.get("status"),
                "symbol": lab.get("symbol"),
                "strike": lab.get("strike"),
                "side": lab.get("side"),
                "entry": lab.get("entry"),
                "gap_pts": lab.get("gap_pts"),
                "exec": (r.get("execution") or {}).get("reason"),
            }, default=str)[:300])
    state = sh / "execution_state.json"
    if state.exists():
        stj = jload(state)
        print("  execution_state", {k: stj.get(k) for k in ("equity","peak_equity","dd_mode","month_halted","month_ce_halt","skip_next_day","month_pnl")})

print("\n==== 6. LAKE SPOT FORENSICS ====")
sys.path.insert(0, str(NIFTY))
sys.path.insert(0, str(BN))
from edge_lab.lake import read_spot, session_dates, partition_parquet
from edge_lab.paths import default_lake as nifty_default_lake

def lake_report(lab_root, und):
    lake = lab_root / "data_lake"
    print("---", und, "lake", lake, "exists", lake.exists())
    if not lake.exists():
        return
    spots = list(lake.glob("asset_class=spot/underlying=*/year=*/month=*/*.parquet"))
    opts = list(lake.glob("asset_class=options/underlying=*/year=*/month=*/*.parquet"))
    print("  spot_parquet", len(spots), "opt_parquet", len(opts))
    for p in sorted(spots)[-6:]:
        print("   ", p.relative_to(lake), "bytes", p.stat().st_size)
    start = date(2026, 7, 1)
    end = IST_DAY
    try:
        df = read_spot(lake, und, start, end)
    except Exception as e:
        print("  read_spot ERROR", type(e).__name__, str(e)[:200])
        return
    days = session_dates(df)
    print("  spot_rows", 0 if df is None or df.empty else len(df), "session_days", len(days), "first", days[0] if days else None, "last", days[-1] if days else None)
    print("  has_target_day", IST_DAY in days)
    if not df.empty and IST_DAY in set(days):
        day_df = df[df["_ts_ist"].dt.date == IST_DAY]
        print("  target_bars", len(day_df), "first", str(day_df["_ts_ist"].iloc[0]) if len(day_df) else None, "last", str(day_df["_ts_ist"].iloc[-1]) if len(day_df) else None)
        # cash window coverage
        hh = day_df["_ts_ist"].dt.hour * 60 + day_df["_ts_ist"].dt.minute
        print("  bars_before_930", int((hh < 9*60+30).sum()), "bars_0930_1000", int(((hh >= 9*60+30) & (hh < 10*60)).sum()), "bars_total_open", int(((hh >= 9*60+15) & (hh <= 15*60+30)).sum()))
    elif days:
        print("  last_3_days", [str(x) for x in days[-3:]])

# NIFTY lab lake
os.chdir(str(NIFTY))
sys.path.insert(0, str(NIFTY))
# re-import paths from nifty
import importlib
import edge_lab.paths as paths_mod
importlib.reload(paths_mod)
lake_report(NIFTY, "NIFTY")

os.chdir(str(BN))
sys.path.insert(0, str(BN))
importlib.reload(paths_mod)
lake_report(BN, "BANKNIFTY")

print("\n==== 7. DESK LOG (schedule / lab / auto today) ====")
log = DESK / "logs/desk.out"
if log.exists():
    hits = []
    for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]:
        low = ln.lower()
        if any(x in low for x in ("schedule", "lab.journal", "auto.place", "shadow", "paper", "no trades", "error", "traceback")):
            hits.append(ln[:220])
    print("matched_tail", len(hits))
    for ln in hits[-40:]:
        print(" ", ln)
else:
    print("no desk.out")

print("\n==== 8. SCRIPT / CONFIG PRESENCE ====")
for p in (
    NIFTY / "scripts/run_shadow_daily.py",
    NIFTY / "scripts/ingest_dhan_nifty.py",
    NIFTY / "config/rungs/paper_2l_nifty_tier2_recommended.yaml",
    BN / "scripts/run_shadow_daily.py",
    BN / "scripts/ingest_dhan_bn.py",
    BN / "config/edge_book_2l_dd20.yaml",
    DESK / "app/lab_sync.py",
):
    print(("OK" if p.exists() else "MISSING"), p, "bytes", p.stat().st_size if p.exists() else 0)
"""


def main() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=os.environ["EDGE_VPS_PASS"], timeout=60, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    helper = f"{CHROOT}/tmp/_forensic_paper.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(
        f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 /tmp/_forensic_paper.py",
        timeout=120,
    )
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-1500:])
    c.close()


if __name__ == "__main__":
    main()
