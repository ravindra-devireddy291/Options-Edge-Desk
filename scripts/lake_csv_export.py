#!/usr/bin/env python3
"""Read a lab data_lake parquet tree → CSV or JSON probe. Run with that lab's venv python."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab-root", required=True)
    ap.add_argument("--underlying", required=True, choices=("NIFTY", "BANKNIFTY"))
    ap.add_argument("--mode", choices=("probe", "csv"), default="csv")
    ap.add_argument("--kind", choices=("spot", "options"), default="spot")
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    root = Path(args.lab_root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from datetime import date as _date

    from edge_lab.lake import read_options, read_spot, session_dates

    start = _date.fromisoformat(args.date_from[:10])
    end = _date.fromisoformat(args.date_to[:10])
    lake = root / "data_lake"
    und = args.underlying
    if args.kind == "options":
        df = read_options(lake, und, start, end)
    else:
        df = read_spot(lake, und, start, end)

    if args.mode == "probe":
        days = session_dates(df) if df is not None and not df.empty else []
        payload = {
            "underlying": und,
            "kind": args.kind,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "exists": lake.exists(),
            "rows": 0 if df is None or df.empty else int(len(df)),
            "last_day": str(days[-1]) if days else None,
            "sessions": [str(x) for x in days[-12:]],
        }
        sys.stdout.write(json.dumps(payload, default=str))
        return 0

    out = Path(args.out) if args.out else None
    if df is None or df.empty:
        text = "ts_ist\n"
    else:
        slim = df.copy()
        if "_ts_ist" in slim.columns:
            slim["ts_ist"] = slim["_ts_ist"].map(lambda x: x.isoformat() if hasattr(x, "isoformat") else str(x))
            slim = slim.drop(columns=["_ts_ist"], errors="ignore")
        elif "timestamp_ns" in slim.columns:
            ts = slim["timestamp_ns"].map(
                lambda n: datetime.utcfromtimestamp(int(n) / 1e9).isoformat() if n == n else ""
            )
            slim.insert(0, "ts_ist", ts)
        text = slim.to_csv(index=False)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
