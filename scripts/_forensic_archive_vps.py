"""Dump paper archive internals + lake last dates. No secrets."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"
INNER = r"""
import json
from pathlib import Path

p = Path("/root/Options-Edge-Desk/data/paper/2026-08-17.json")
d = json.loads(p.read_text(encoding="utf-8"))
trades = d.get("trades") if isinstance(d.get("trades"), dict) else {}
signals = d.get("signals") if isinstance(d.get("signals"), dict) else {}
print("TOP", json.dumps({
    "saved_at": d.get("saved_at"),
    "reason": d.get("reason"),
    "mode": d.get("mode"),
    "execution": d.get("execution"),
    "trade_count_field": d.get("trade_count"),
    "signal_count_field": d.get("signal_count"),
    "note": d.get("note"),
    "trades_inner_count": (trades or {}).get("trade_count"),
    "trades_list_len": len(trades.get("trades") or []) if isinstance(trades, dict) else None,
    "signals_inner_count": (signals or {}).get("count"),
    "signals_list_len": len(signals.get("signals") or []) if isinstance(signals, dict) else None,
    "positions_rows": (d.get("positions") or {}).get("row_count") if isinstance(d.get("positions"), dict) else None,
    "orders_open": (d.get("orders_open") or {}).get("count") if isinstance(d.get("orders_open"), dict) else None,
    "dhan_trade_book_len": len(d.get("dhan_trade_book") or []) if isinstance(d.get("dhan_trade_book"), list) else type(d.get("dhan_trade_book")).__name__,
}, default=str))
print("TRADES_SUMMARY", json.dumps({k: trades.get(k) for k in ("day","trade_count","closed_count","total_realized_pnl","total_net_pnl","lots_traded")}, default=str))
print("SIGNALS_SUMMARY", json.dumps({k: signals.get(k) for k in ("count","day") if k in (signals or {})} | {"statuses": {}}, default=str))
from collections import Counter
st = Counter(str(s.get("status")) for s in (signals.get("signals") or []))
print("SIGNAL_STATUSES", dict(st))
for s in (signals.get("signals") or [])[:10]:
    print("SIG", json.dumps({k: s.get(k) for k in ("signal_id","underlying","sleeve","status","symbol","notes","target_strike")}, default=str)[:260])
for t in (trades.get("trades") or [])[:10]:
    print("TRD", json.dumps({k: t.get(k) for k in ("underlying","symbol","realized_pnl","exit_reason","broker_entry","lab_entry")}, default=str)[:260])
pos_rows = (d.get("positions") or {}).get("rows") or []
print("POS_N", len(pos_rows))
for r in pos_rows[:8]:
    print("POS", json.dumps({k: r.get(k) for k in ("underlying","symbol","qty","lots","product","unrealized_pnl")}, default=str)[:220])
tb = d.get("dhan_trade_book") or []
print("DHAN_TB_N", len(tb) if isinstance(tb, list) else tb)
if isinstance(tb, list):
    for r in tb[:8]:
        print("DHAN_TB", json.dumps({k: r.get(k) for k in ("tradingSymbol","transactionType","tradedQuantity","tradedPrice","exchangeTime")}, default=str)[:240])

print("\n==== LAKE FILES LAST DATES ====")
lake = Path("/root/Options-Edge-Lab/data_lake")
for ac in ("spot", "options"):
    unds = sorted({p.parent.parent.parent.name for p in lake.glob(f"asset_class={ac}/underlying=*")})
    print(ac, "underlyings", unds)
    for u in unds:
        parts = sorted(lake.glob(f"asset_class={ac}/{u}/year=*/month=*/*.parquet"))
        print(" ", u, "n", len(parts), "last", str(parts[-1].relative_to(lake)) if parts else None, "bytes", parts[-1].stat().st_size if parts else 0)

# pandas last session from BN lake NIFTY and BANKNIFTY
import pandas as pd
from datetime import date, timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30))
def last_days(und):
    frames = []
    for p in sorted(lake.glob(f"asset_class=spot/underlying={und}/year=2026/month=*/*.parquet"))[-3:]:
        try:
            frames.append(pd.read_parquet(p))
        except Exception as e:
            print("  read fail", p, e)
    if not frames:
        print(und, "NO_SPOT")
        return
    df = pd.concat(frames, ignore_index=True)
    ts = pd.to_datetime(df["timestamp_ns"], unit="ns", utc=True).dt.tz_convert(IST)
    days = sorted(set(ts.dt.date.tolist()))
    print(und, "rows_last3m", len(df), "days", len(days), "first", days[0], "last", days[-1], "has_0817", date(2026,8,17) in days, "has_0814", date(2026,8,14) in days)
    print("  last5", [str(x) for x in days[-5:]])

last_days("NIFTY")
last_days("BANKNIFTY")

nifty_own = Path("/root/Options-Nifty-Edge-Lab/data_lake")
print("nifty_own_children", [p.name for p in nifty_own.iterdir()] if nifty_own.exists() else None)
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
    helper = f"{CHROOT}/tmp/_forensic_archive.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 /tmp/_forensic_archive.py", timeout=90)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-1200:])
    c.close()

if __name__ == "__main__":
    main()
