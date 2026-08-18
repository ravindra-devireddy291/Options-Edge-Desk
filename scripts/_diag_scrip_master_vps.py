"""Diagnose Dhan scrip-master parse for BANKNIFTY on VPS."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"
INNER = r"""
import os, sys
from datetime import date
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/root/Options-Edge-Desk")
os.chdir("/root/Options-Edge-Desk")
from app.brokers.dhan.contracts import CACHE_PATH, _ensure_master, _load_master, option_rows, _pick, _parse_expiry

path = _ensure_master(force=True)
print("cache", path, "bytes", path.stat().st_size)
rows = _load_master(force=False)
print("master_rows", len(rows))
print("cols", list(rows[0].keys())[:25] if rows else None)
bn = option_rows("BANKNIFTY")
print("bn_option_rows", len(bn))
if bn:
    exps = sorted({r["expiry"] for r in bn})
    print("expiry_min", exps[0], "expiry_max", exps[-1], "n_exp", len(exps))
    print("exps", [str(x) for x in exps[:12]])
    day = date(2026,8,17)
    live = [r for r in bn if r["expiry"] >= day]
    print("live_ge_day", len(live))
    ce = [r for r in live if r["option_type"]=="CE"]
    strikes = sorted({r["strike"] for r in ce})
    print("live_ce", len(ce), "strike_min", strikes[0] if strikes else None, "strike_max", strikes[-1] if strikes else None)
    near = [s for s in strikes if abs(s-57400) <= 500]
    print("strikes_near_57400", near[:20])
else:
    # why empty? sample OPTIDX
    inst_n = 0
    bn_sym = 0
    for r in rows[:5000]:
        inst = _pick(r, "SEM_INSTRUMENT_NAME", "INSTRUMENT").upper()
        if inst == "OPTIDX":
            inst_n += 1
            sym = _pick(r, "SEM_TRADING_SYMBOL", "TRADING_SYMBOL", "SEM_CUSTOM_SYMBOL", "DISPLAY_NAME", "SYMBOL_NAME")
            if "BANKNIFTY" in (sym or "").upper():
                bn_sym += 1
                if bn_sym <= 3:
                    print("sample_bn", {k: r.get(k) for k in list(r)[:12]}, "sym", sym)
    print("optidx_in_first_5k", inst_n, "banknifty_sym", bn_sym)
    # scan all for BANKNIFTY
    n = 0
    sample = None
    for r in rows:
        blob = " ".join((r.get(k) or "") for k in r).upper()
        if "BANKNIFTY" in blob:
            n += 1
            if sample is None:
                sample = r
    print("any_banknifty_rows", n)
    if sample:
        print("sample_keys", list(sample.keys()))
        print("sample", {k: sample[k] for k in list(sample)[:20]})
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
    helper = f"{CHROOT}/tmp/_diag_master.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 /tmp/_diag_master.py", timeout=180)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-1200:])
    c.close()

if __name__ == "__main__":
    main()
