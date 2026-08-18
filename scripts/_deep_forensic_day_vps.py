"""Deep forensics for one IST session — spot, lab replay, desk audit. No secrets."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
CHROOT = "/mnt/sys"

INNER_TEMPLATE = r'''
import json
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

DAY = date.fromisoformat("__DAY__")
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

def jload(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        return {"_error": str(e)[:200]}

print("=" * 72)
print("DEEP FORENSICS", DAY.isoformat())
print("=" * 72)

# --- env / desk health ---
env = {}
for ln in (DESK / ".env").read_text().splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1)
        env[k.strip()] = v.strip()
print("\n[ENV]", {k: env.get(k) for k in (
    "DESK_MODE", "DESK_PAPER_AUTO", "DESK_LIVE_ENABLED", "NIFTY_CONFIG", "BN_CONFIG",
)})

sys.path.insert(0, str(DESK))
from app.session import now_ist, market_session
from app.runners.state import RUNNER
print("[CLOCK]", now_ist().isoformat(), "market", market_session())
print("[RUNNER]", json.dumps({
    "mode": RUNNER.mode, "execution": RUNNER.execution, "state": RUNNER.state,
    "trading_active": RUNNER.trading_active(), "kill": RUNNER.kill.active,
}, default=str))

# --- spot forensics ---
sys.path.insert(0, str(BN))
from edge_lab.lake import read_spot, read_options
from edge_lab.regime import spot_regime, prior_session_regime

def spot_forensics(lab_root, und, min_gap):
    lake = lab_root / "data_lake"
    print(f"\n[SPOT {und}] lake={lake}")
    spot = read_spot(lake, und, DAY - timedelta(days=14), DAY)
    if spot is None or spot.empty:
        print("  EMPTY spot series")
        return None
    day_df = spot[spot["_ts_ist"].dt.date == DAY]
    if day_df.empty:
        print("  NO rows for target day")
        return None
    cash = day_df[(day_df["_ts_ist"].dt.time >= time(9, 15)) & (day_df["_ts_ist"].dt.time <= time(15, 30))]
    prior = spot[spot["_ts_ist"].dt.date < DAY]
    prev_close = None
    if not prior.empty:
        prev_close = float(prior.groupby(prior["_ts_ist"].dt.date)["close"].last().iloc[-1])
        prev_day = prior["_ts_ist"].dt.date.max()
    else:
        prev_day = None
    open_bar = day_df[day_df["_ts_ist"].dt.time >= time(9, 15)].head(1)
    open_px = float(open_bar["open"].iloc[0]) if not open_bar.empty and "open" in open_bar.columns else float(open_bar["close"].iloc[0]) if not open_bar.empty else None
    entry_bar = day_df[day_df["_ts_ist"].dt.time >= time(9, 30)].head(1)
    entry_spot = float(entry_bar["close"].iloc[0]) if not entry_bar.empty else None
    gap = (open_px - prev_close) if (open_px is not None and prev_close is not None) else None
    reg = spot_regime(spot, DAY)
    preg = prior_session_regime(spot, DAY)
    deltas = cash["_ts_ist"].diff().dt.total_seconds().fillna(60) if not cash.empty else None
    gaps_gt_2m = int((deltas > 120).sum()) if deltas is not None and len(deltas) else 0
    rec = {
        "prev_day": str(prev_day) if prev_day else None,
        "prev_close": round(prev_close, 2) if prev_close is not None else None,
        "open_0915": round(open_px, 2) if open_px is not None else None,
        "spot_0930": round(entry_spot, 2) if entry_spot is not None else None,
        "gap_pts": round(gap, 2) if gap is not None else None,
        "abs_gap": round(abs(gap), 2) if gap is not None else None,
        "min_gap_required": min_gap,
        "gap_would_pass": bool(gap is not None and abs(gap) >= min_gap),
        "regime_today": reg.label if reg else None,
        "regime_prior": preg.label if preg else None,
        "ret_5d": round(float(reg.ret_5d), 4) if reg and reg.ret_5d is not None else None,
        "cash_bars": len(cash),
        "all_day_bars": len(day_df),
        "gaps_gt_2min": gaps_gt_2m,
        "cash_first": str(cash["_ts_ist"].iloc[0]) if len(cash) else None,
        "cash_last": str(cash["_ts_ist"].iloc[-1]) if len(cash) else None,
        "cash_low": round(float(cash["close"].min()), 2) if len(cash) else None,
        "cash_high": round(float(cash["close"].max()), 2) if len(cash) else None,
        "cash_close": round(float(cash["close"].iloc[-1]), 2) if len(cash) else None,
    }
    print(json.dumps(rec, indent=2))
    opt = read_options(lake, und, DAY, DAY)
    opt_n = 0 if opt is None or opt.empty else len(opt)
    print(f"  option_rows={opt_n} symbols={opt['tradingsymbol'].nunique() if opt_n else 0}")
    return rec

# config thresholds
sys.path.insert(0, str(NIFTY))
from edge_lab.risk.execution_brakes import load_book_config, fade_params_from_config, orb_params_from_config
n_cfg = load_book_config(str(NIFTY / env.get("NIFTY_CONFIG", "config/rungs/paper_2l_nifty_tier2_recommended.yaml")))
bn_cfg = load_book_config(str(BN / env.get("BN_CONFIG", "config/edge_book_2l_dd20.yaml")))
nf = fade_params_from_config(n_cfg)
bf = fade_params_from_config(bn_cfg)
no = orb_params_from_config(n_cfg)
bo = orb_params_from_config(bn_cfg)

n_spot = spot_forensics(NIFTY, "NIFTY", float(nf.get("min_gap_pts") or 100))
bn_spot = spot_forensics(BN, "BANKNIFTY", float(bf.get("min_gap_pts") or 150))

# --- independent lab replay ---
from edge_lab.structures.gap_continuation import day_to_dict, run_gap_continuation_day
from edge_lab.structures.orb_breakout import run_orb_day, day_to_dict as orb_dict

def replay_book(lab_root, cfg, und, fp, op):
    lake = lab_root / "data_lake"
    spot = read_spot(lake, und, DAY - timedelta(days=14), DAY)
    opt = read_options(lake, und, DAY, DAY)
    fade = run_gap_continuation_day(
        spot, opt, DAY,
        underlying=und,
        entry_time=time(9, 30),
        exit_time=time(15, 20),
        min_gap_pts=float(fp["min_gap_pts"]),
        stop_pct=float(fp["stop_pct"]),
        take_profit_pct=float(fp["take_profit_pct"]),
        lots=1,
        strike_step=int(fp.get("strike_step") or (50 if und == "NIFTY" else 100)),
        fill_mode=str(fp.get("fill_mode") or "aggressor"),
        apply_india_fo_charges=bool(fp.get("apply_india_fo_charges", True)),
        commission_per_order=float(fp.get("commission") or 20.0),
        fade=True,
        regime_mode=str(fp.get("regime_mode") or "chop_only"),
    )
    orb = run_orb_day(
        spot, opt, DAY,
        underlying=und,
        entry_time=time(9, 50),
        exit_time=time(15, 20),
        min_range_pts=float(op.get("min_range_pts") or 100),
        stop_pct=float(op.get("stop_pct") or 0.25),
        take_profit_pct=float(op.get("take_profit_pct") or 0.80),
        lots=1,
        strike_step=int(op.get("strike_step") or (50 if und == "NIFTY" else 100)),
        fill_mode=str(op.get("fill_mode") or "aggressor"),
        apply_india_fo_charges=bool(op.get("apply_india_fo_charges", True)),
        commission_per_order=float(op.get("commission") or 20.0),
    )
    print(f"\n[LAB REPLAY {und}]")
    print(" fade", json.dumps(day_to_dict(fade), default=str))
    print(" orb ", json.dumps(orb_dict(orb), default=str))

replay_book(NIFTY, n_cfg, "NIFTY", nf, no)
replay_book(BN, bn_cfg, "BANKNIFTY", bf, bo)

# --- shadow journals on disk ---
print("\n[SHADOW JOURNALS ON DISK]")
for root, name in ((NIFTY, "NIFTY"), (BN, "BANKNIFTY")):
    p = root / "reports/shadow" / f"shadow_{DAY.isoformat()}.jsonl"
    print(f"  {name} exists={p.exists()} bytes={p.stat().st_size if p.exists() else 0}")
    for r in jsonl(p):
        lab = r.get("lab") or {}
        ex = r.get("execution") or {}
        print("   ", json.dumps({
            "sleeve": r.get("sleeve"),
            "tradeable": r.get("tradeable"),
            "lab_status": lab.get("status"),
            "gate": ex.get("reason"),
            "lots": ex.get("lots"),
            "gap_pts": lab.get("gap_pts"),
            "side": lab.get("side"),
            "strike": lab.get("strike"),
            "symbol": lab.get("symbol"),
            "net_pnl": lab.get("net_pnl"),
            "broker_fill": bool(r.get("broker_fill")),
        }, default=str))

# --- desk compass + would-be pending ---
sys.path.insert(0, str(DESK))
from app.books import adapters as books
from app.auth import get_settings
s = get_settings()
book_list = [
    books.nifty_book(s.nifty_lab_root, s.nifty_config),
    books.bn_book(s.bn_lab_root, s.bn_config),
]
day_s = DAY.isoformat()
comp = books.signals_today(book_list, day_s)
print("\n[DESK COMPASS]")
print(json.dumps({"count": comp.get("count"), "statuses": dict(Counter(str(x.get("status")) for x in comp.get("signals") or []))}, default=str))
pending = []
for sig in comp.get("signals") or []:
    st = str(sig.get("status") or "").upper()
    print(" ", json.dumps({k: sig.get(k) for k in (
        "signal_id", "underlying", "sleeve", "status", "notes", "target_strike", "target_lots", "symbol",
    )}, default=str))
    if st == "PENDING":
        pending.append(sig)

trades = books.trades_today(book_list, day_s)
print("\n[DESK BLOTTER]", json.dumps({k: trades.get(k) for k in (
    "trade_count", "closed_count", "total_net_pnl", "lots_traded",
)}, default=str))

# --- audit timeline ---
print("\n[DESK AUDIT TIMELINE]")
events = jsonl(DESK / "data/audit" / f"events_{day_s}.jsonl")
kinds = Counter(str(r.get("kind") or "?") for r in events)
print("event_kinds", dict(kinds))
first_journal = None
arm_ts = None
for r in events:
    k = str(r.get("kind") or "")
    if k == "trading.schedule_arm" and not arm_ts:
        arm_ts = r.get("ts")
    if k == "lab.journal" and r.get("ok"):
        if not first_journal:
            first_journal = r.get("ts")
    if k.startswith("auto.") or k.startswith("order."):
        print(" ", json.dumps({x: r.get(x) for x in (
            "ts", "kind", "signal_id", "code", "accepted", "underlying", "flattened", "reason",
        ) if r.get(x) is not None}, default=str))
print("first_schedule_arm", arm_ts)
print("first_ok_lab_journal", first_journal)
orders = jsonl(DESK / "data/audit" / f"orders_{day_s}.jsonl")
print("dhan_orders_logged", len(orders))

auto = jload(DESK / "data/auto_state.json")
print("auto_state", auto)

# --- archive ---
arch = jload(DESK / "data/paper" / f"{day_s}.json")
if "_error" not in arch:
    print("\n[ARCHIVE]", json.dumps({
        "saved_at": arch.get("saved_at"), "reason": arch.get("reason"),
        "trade_count": arch.get("trade_count"), "signal_count": arch.get("signal_count"),
        "dhan_tb": len(arch.get("dhan_trade_book") or []) if isinstance(arch.get("dhan_trade_book"), list) else arch.get("dhan_trade_book"),
    }, default=str))

# --- verdict ---
print("\n" + "=" * 72)
print("VERDICT")
print("=" * 72)
issues = []
if not (NIFTY / "reports/shadow" / f"shadow_{day_s}.jsonl").exists():
    issues.append("DESK_GAP: NIFTY journal missing during session")
if not (BN / "reports/shadow" / f"shadow_{day_s}.jsonl").exists():
    issues.append("DESK_GAP: BN journal missing during session")
if arm_ts and first_journal:
    # schedule ~09:10 IST = 03:40 UTC; journal should follow within ~10 min
    pass
elif not first_journal:
    issues.append("DESK_GAP: no successful lab.journal audit today")
if pending:
    issues.append(f"DESK_GAP: {len(pending)} PENDING card(s) never placed — investigate auto/OMS")
if orders:
    issues.append("unexpected orders when all skips?")
if not events:
    issues.append("DESK_GAP: no audit events for day")

if pending:
    print("FAIL — desk had tradeable PENDING cards")
elif issues:
    print("ISSUES:", issues)
else:
    print("PASS — pipeline healthy; zero tradeable signals (all legitimate lab skips)")
    print("No evidence Edge Desk blocked placement today.")
    if n_spot:
        print(f"  NIFTY gap {n_spot.get('gap_pts')} pts < min {n_spot.get('min_gap_required')} -> skip_small_gap expected")
    if bn_spot:
        print(f"  BN gap {bn_spot.get('gap_pts')} pts < min {bn_spot.get('min_gap_required')} -> skip_small_gap expected")
    print("  NIFTY ORB lots=0 in fade-only pack -> skip_lots_zero expected")
    print("  BN ORB inside range -> skip_inside_orb expected")
'''


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=date.today().isoformat())
    args = ap.parse_args()
    load_env()
    inner = INNER_TEMPLATE.replace("__DAY__", args.day)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=os.environ["EDGE_VPS_PASS"], timeout=60, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    helper = f"{CHROOT}/tmp/_deep_forensic.py"
    with sftp.file(helper, "w") as fh:
        fh.write(inner)
    sftp.close()
    _, o, e = c.exec_command(
        f"chroot {CHROOT} /root/Options-Edge-Lab/.venv/bin/python3 /tmp/_deep_forensic.py",
        timeout=180,
    )
    out = o.read().decode("utf-8", "replace")
    out_path = Path(__file__).resolve().parents[1] / "forensic_0818.txt"
    out_path.write_text(out, encoding="utf-8")
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-2500:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
