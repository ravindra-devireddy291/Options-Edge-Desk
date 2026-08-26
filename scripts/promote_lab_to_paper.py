"""One-shot: lab ok shadow cards → desk_paper fills for client Trades/Book."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for p in (ROOT / ".env", ROOT / ".env.local"):
    if not p.exists():
        continue
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

from app.auth import get_settings
from app.books.adapters import bn_book, nifty_book, trades_today
from app.books.lab_to_paper import promote_range
from app.books.live_cutover import g5_sessions


def main() -> int:
    s = get_settings()
    books = [nifty_book(s.nifty_lab_root, s.nifty_config), bn_book(s.bn_lab_root, s.bn_config)]
    force = "--force" in sys.argv
    result = promote_range(books, force=force)
    print(json.dumps(result, indent=2))
    print("--- blotter check ---")
    for b in books:
        print(b.name, "G5", g5_sessions(b), "/20")
    # today + sample history nets
    from datetime import date, timedelta
    from app.session import session_day

    end = session_day()
    start = end - timedelta(days=10)
    d = start
    while d <= end:
        if d.weekday() < 5:
            for b in books:
                t = trades_today([b], d.isoformat())
                if t["trade_count"]:
                    print(
                        d,
                        b.name,
                        "trades",
                        t["trade_count"],
                        "closed",
                        t["closed_count"],
                        "net",
                        t["total_net_pnl"],
                    )
        d += timedelta(days=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
