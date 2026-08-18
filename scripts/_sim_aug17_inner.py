"""Inner: dump 2026-08-17 journals and replay BN fade on the lake. No orders."""
from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

import pandas as pd

DAY = date(2026, 8, 17)
KEEP_LAB = [
    "status",
    "side",
    "strike",
    "symbol",
    "entry",
    "exit",
    "qty",
    "lots",
    "lot_size",
    "gross_pnl",
    "net_pnl",
    "exit_reason",
    "gap_pts",
    "costs_inr",
    "ltp",
    "action",
    "notes",
    "expiry",
    "spot",
]


def main() -> None:
    paths = [
        Path("/root/Options-Nifty-Edge-Lab/reports/shadow/shadow_2026-08-17.jsonl"),
        Path("/root/Options-Edge-Lab/reports/shadow/shadow_2026-08-17.jsonl"),
    ]
    cards = []
    for p in paths:
        book = "NIFTY" if "Nifty" in str(p) else "BANKNIFTY"
        if not p.exists():
            cards.append({"book": book, "error": "missing journal"})
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            lab = r.get("lab") or {}
            ex = r.get("execution") or {}
            cards.append(
                {
                    "book": book,
                    "sleeve": r.get("sleeve"),
                    "tradeable": r.get("tradeable"),
                    "gate": ex.get("reason"),
                    "lots_gate": ex.get("lots"),
                    "lab": {k: lab.get(k) for k in KEEP_LAB},
                }
            )
    print("CARDS", json.dumps(cards, default=str))

    import sys

    sys.path.insert(0, "/root/Options-Edge-Lab")
    from edge_lab.fills import fill_price
    from edge_lab.lake import read_options, read_spot
    from edge_lab.risk.execution_brakes import fade_params_from_config, load_book_config
    from edge_lab.structures.common import leg_path
    from edge_lab.structures.gap_continuation import day_to_dict, run_gap_continuation_day

    cfg = load_book_config("/root/Options-Edge-Lab/config/edge_book_2l_dd20.yaml")
    fp = fade_params_from_config(cfg)
    lake = Path("/root/Options-Edge-Lab/data_lake")
    from datetime import timedelta

    spot = read_spot(lake, "BANKNIFTY", DAY - timedelta(days=14), DAY)
    opt = read_options(lake, "BANKNIFTY", DAY, DAY)
    if opt is not None and not opt.empty:
        ce = opt[(opt["strike"] == 57400) & (opt["instrument_type"].astype(str).str.upper() == "CE")]
        uniq = (
            ce.groupby(["tradingsymbol", "expiry"] if "expiry" in ce.columns else ["tradingsymbol"])
            .size()
            .reset_index(name="n")
        )
        print("CHAIN_57400_CE", uniq.head(20).to_json(orient="records", default_handler=str))
        print("OPT_COLS", list(opt.columns))
        print("N_SYMBOLS_DAY", int(opt["tradingsymbol"].nunique()) if "tradingsymbol" in opt.columns else 0)
    trade = run_gap_continuation_day(
        spot,
        opt,
        DAY,
        underlying="BANKNIFTY",
        entry_time=time(9, 30),
        exit_time=time(15, 20),
        min_gap_pts=float(fp["min_gap_pts"]),
        stop_pct=float(fp["stop_pct"]),
        take_profit_pct=float(fp["take_profit_pct"]),
        lots=1,
        strike_step=int(fp.get("strike_step") or 100),
        fill_mode=str(fp.get("fill_mode") or "aggressor"),
        apply_india_fo_charges=bool(fp.get("apply_india_fo_charges", True)),
        commission_per_order=float(fp.get("commission") or 20.0),
        fade=True,
        regime_mode=str(fp.get("regime_mode") or "chop_only"),
    )
    td = day_to_dict(trade)
    print("REPLAY", json.dumps(td, default=str))

    symbol = td.get("symbol") or ""
    entry = float(td.get("entry") or 0)
    stop = entry * (1.0 - float(fp["stop_pct"])) if entry else None
    tp = entry * (1.0 + float(fp["take_profit_pct"])) if entry else None
    path = leg_path(opt, DAY, symbol, time(9, 30), time(15, 20)) if symbol else None
    samples = []
    if path is not None and not path.empty:
        for i, row in path.iterrows():
            mm = row["_ts_ist"].strftime("%H:%M")
            keep = mm.endswith("0") or mm.endswith("5") or i == path.index[0] or i == path.index[-1]
            if not keep:
                continue
            ser = pd.Series({"bid": row.get("bid"), "ask": row.get("ask"), "close": row.get("close")})
            try:
                sell = fill_price(ser, side="sell", mode="aggressor")
            except Exception:
                sell = float(row["close"]) if pd.notna(row.get("close")) else None
            samples.append(
                {
                    "t": mm,
                    "bid": None if pd.isna(row.get("bid")) else round(float(row["bid"]), 2),
                    "ask": None if pd.isna(row.get("ask")) else round(float(row["ask"]), 2),
                    "close": None if pd.isna(row.get("close")) else round(float(row["close"]), 2),
                    "sell": None if sell is None else round(float(sell), 2),
                }
            )
    lot_hint = None
    if path is not None and not path.empty and "lot_size" in path.columns:
        lot_hint = int(path.iloc[0]["lot_size"])
    print(
        "PATH_META",
        json.dumps(
            {
                "symbol": symbol,
                "bars": 0 if path is None or path.empty else int(len(path)),
                "stop": None if stop is None else round(stop, 2),
                "tp": None if tp is None else round(tp, 2),
                "stop_pct": fp["stop_pct"],
                "take_profit_pct": fp["take_profit_pct"],
                "fill_mode": fp.get("fill_mode"),
                "lot_hint": lot_hint,
            },
            default=str,
        ),
    )
    print("PATH", json.dumps(samples, default=str))


if __name__ == "__main__":
    main()
