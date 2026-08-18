"""Cash-window sanity on the 2026-08-17 spot we just ingested."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"
INNER = r"""
from datetime import date, time
from pathlib import Path
import sys
sys.path.insert(0, "/root/Options-Nifty-Edge-Lab")
from edge_lab.lake import read_spot

def report(lake, und):
    df = read_spot(Path(lake), und, date(2026,8,17), date(2026,8,17))
    if df is None or df.empty:
        print(und, "EMPTY")
        return
    t = df["_ts_ist"]
    cash = df[(t.dt.time >= time(9,15)) & (t.dt.time <= time(15,30))]
    print(und, "all", len(df), "cash_0915_1530", len(cash))
    if cash.empty:
        print("  NO CASH BARS")
        return
    print("  cash_first", str(cash["_ts_ist"].iloc[0]), "o", float(cash["open"].iloc[0]), "c", float(cash["close"].iloc[0]))
    print("  cash_last", str(cash["_ts_ist"].iloc[-1]), "o", float(cash["open"].iloc[-1]), "c", float(cash["close"].iloc[-1]))
    # gaps > 2 min
    deltas = cash["_ts_ist"].diff().dt.total_seconds().fillna(60)
    gaps = int((deltas > 120).sum())
    print("  gaps_gt_2min", gaps, "min_close", float(cash["close"].min()), "max_close", float(cash["close"].max()))
    after = df[t.dt.time > time(15,30)]
    print("  after_1530_bars", len(after), "last_all", str(df["_ts_ist"].iloc[-1]), "last_close", float(df["close"].iloc[-1]))

report("/root/Options-Nifty-Edge-Lab/data_lake", "NIFTY")
report("/root/Options-Edge-Lab/data_lake", "BANKNIFTY")
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
    helper = f"{CHROOT}/tmp/_forensic_bars.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 /tmp/_forensic_bars.py", timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-800:])
    c.close()

if __name__ == "__main__":
    main()
