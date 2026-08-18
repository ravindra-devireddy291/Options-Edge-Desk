"""Today's paper session review — 2026-08-18. No secrets."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"
DAY = date.today().isoformat()


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


INNER = r'''
import json
from collections import Counter
from datetime import date
from pathlib import Path
import urllib.request

DAY = "__DAY__"
DESK = Path("/root/Options-Edge-Desk")
NIFTY = Path("/root/Options-Nifty-Edge-Lab")
BN = Path("/root/Options-Edge-Lab")

def jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out

env = {}
for ln in (DESK / ".env").read_text().splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        env[k.strip()] = v.strip()
key = env.get("DESK_API_KEY", "")

import sys
sys.path.insert(0, str(DESK))
from app.session import now_ist, market_session, session_day
from app.runners.state import RUNNER

print("==== CLOCK ====")
print(json.dumps({
    "now_ist": now_ist().isoformat(),
    "session_day": session_day().isoformat(),
    "market_session": market_session(),
    "runner": {
        "mode": RUNNER.mode,
        "execution": RUNNER.execution,
        "state": RUNNER.state,
        "trading_active": RUNNER.trading_active(),
        "kill": RUNNER.kill.active,
        "last_error": (RUNNER.last_error or "")[:200],
    },
}, default=str))

print("\n==== DESK API ====")
for ep in ("/healthz", "/api/v1/desk/status", "/api/v1/desk/signals/today", "/api/v1/desk/trades/today"):
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8080" + ep,
            headers={"X-API-Key": key},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        data = d.get("data") if isinstance(d.get("data"), dict) else d
        if ep.endswith("status"):
            print("STATUS", json.dumps({k: data.get(k) for k in (
                "mode", "execution", "trading_active", "runner_state", "market_session",
                "token_ok", "broker_reachable", "live_enabled", "open_positions",
                "lab_journal", "last_error",
            )}, default=str))
        elif ep.endswith("signals/today"):
            sigs = data.get("signals") or []
            st = Counter(str(s.get("status")) for s in sigs)
            print("COMPASS", json.dumps({"count": data.get("count"), "statuses": dict(st)}, default=str))
            for s in sigs:
                print(" CARD", json.dumps({k: s.get(k) for k in (
                    "signal_id", "underlying", "sleeve", "status", "notes", "symbol",
                    "target_strike", "target_lots", "option_type",
                )}, default=str)[:280])
        elif ep.endswith("trades/today"):
            print("TRADES", json.dumps({k: data.get(k) for k in (
                "day", "trade_count", "closed_count", "total_realized_pnl", "total_net_pnl", "lots_traded",
            )}, default=str))
            for t in (data.get("trades") or [])[:10]:
                print(" TRD", json.dumps({k: t.get(k) for k in (
                    "underlying", "symbol", "lots", "entry_price", "exit_price",
                    "realized_pnl", "net_pnl", "exit_reason", "status",
                )}, default=str)[:280])
        else:
            print(ep, r.status)
    except Exception as e:
        print("ERR", ep, str(e)[:120])

print("\n==== PAPER ARCHIVE ====")
arch = DESK / "data/paper" / f"{DAY}.json"
if arch.exists():
    d = json.loads(arch.read_text(encoding="utf-8"))
    print("ARCHIVE", json.dumps({
        "saved_at": d.get("saved_at"),
        "reason": d.get("reason"),
        "mode": d.get("mode"),
        "trade_count": d.get("trade_count"),
        "signal_count": d.get("signal_count"),
    }, default=str))
    sigs = (d.get("signals") or {}).get("signals") or []
    print("ARCH_SIGNALS", Counter(str(s.get("status")) for s in sigs))
    trades = (d.get("trades") or {}).get("trades") or []
    print("ARCH_TRADES_N", len(trades))
    tb = d.get("dhan_trade_book") or []
    print("DHAN_TB_N", len(tb) if isinstance(tb, list) else type(tb).__name__)
else:
    print("ARCHIVE missing", arch)

print("\n==== AUDIT EVENTS ====")
events = jsonl(DESK / "data/audit" / f"events_{DAY}.jsonl")
print("events_n", len(events), "kinds", dict(Counter(str(r.get("kind") or "?") for r in events)))
for r in events:
    k = str(r.get("kind") or "")
    if any(x in k for x in ("schedule", "lab.", "auto.", "order.", "trading.", "kill")):
        print(" ", json.dumps({x: r.get(x) for x in (
            "ts", "kind", "reason", "mode", "ok", "nifty", "bn", "signal_id",
            "code", "accepted", "underlying", "flattened",
        ) if r.get(x) is not None}, default=str)[:300])

orders = jsonl(DESK / "data/audit" / f"orders_{DAY}.jsonl")
print("orders_n", len(orders))
for r in orders[:15]:
    print(" ORD", json.dumps({k: r.get(k) for k in (
        "ts", "state", "underlying", "side", "mode", "accepted", "code", "client_order_id",
    ) if r.get(k) is not None}, default=str)[:260])

print("\n==== AUTO STATE ====")
auto = DESK / "data/auto_state.json"
print(auto.read_text()[:500] if auto.exists() else "missing")

print("\n==== SHADOW JOURNALS ====")
for root, name in ((NIFTY, "NIFTY"), (BN, "BANKNIFTY")):
    p = root / "reports/shadow" / f"shadow_{DAY}.jsonl"
    print(name, "exists", p.exists(), "bytes", p.stat().st_size if p.exists() else 0)
    if not p.exists():
        continue
    rows = jsonl(p)
    for r in rows:
        lab = r.get("lab") or {}
        ex = r.get("execution") or {}
        bf = r.get("broker_fill")
        print(" ", json.dumps({
            "sleeve": r.get("sleeve"),
            "tradeable": r.get("tradeable"),
            "lab_status": lab.get("status"),
            "gate": ex.get("reason"),
            "lots": ex.get("lots"),
            "side": lab.get("side"),
            "strike": lab.get("strike"),
            "symbol": lab.get("symbol"),
            "entry": lab.get("entry"),
            "exit_reason": lab.get("exit_reason"),
            "net_pnl": lab.get("net_pnl"),
            "broker_fill": bool(bf),
        }, default=str)[:320])

print("\n==== LAKE SPOT BARS ====")
sys.path.insert(0, str(BN))
try:
    from edge_lab.lake import read_spot, session_dates
    d = date.fromisoformat(DAY)
    for name, root, und in (
        ("NIFTY", NIFTY, "NIFTY"),
        ("BANKNIFTY", BN, "BANKNIFTY"),
    ):
        lake = root / "data_lake"
        try:
            spot = read_spot(lake, und, d, d)
            n = 0 if spot is None or spot.empty else len(spot)
            days = [] if spot is None or spot.empty else [str(x) for x in session_dates(spot)]
            print(name, "spot_bars", n, "sessions", days)
        except Exception as e:
            print(name, "lake_err", str(e)[:120])
except Exception as e:
    print("lake_import_err", str(e)[:120])
'''.replace("__DAY__", DAY)


def main() -> int:
    load_env()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=os.environ["EDGE_VPS_PASS"], timeout=60, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    helper = f"{CHROOT}/tmp/_review_today.py"
    with sftp.file(helper, "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 /tmp/_review_today.py", timeout=120)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-1500:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
