#!/usr/bin/env python3
"""Smoke contract resolve + dry_run paper OMS for NIFTY and BANKNIFTY."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DESK_API_KEY", "test")
os.environ.setdefault("NIFTY_LAB_ROOT", r"D:\Options-Nifty-Edge-Lab")
os.environ.setdefault("BN_LAB_ROOT", r"D:\Options-Edge-Lab")

from app.brokers.dhan.contracts import exchange_qty, resolve_contract
from app.books import adapters as books
from app.books import shadow_oms


def main() -> int:
    # BN historical-style resolve by strike/side (uses live master expiries)
    try:
        c_bn = resolve_contract(
            underlying="BANKNIFTY",
            strike=55000,
            option_type="CE",
        )
        print("BN contract", c_bn.as_dict())
        q, lots, ls = exchange_qty(lots=1, lot_size=c_bn.lot_size)
        print("BN qty", q, "lots", lots, "lot_size", ls)
    except Exception as e:
        print("BN resolve FAIL", e)
        return 1

    try:
        c_nf = resolve_contract(
            underlying="NIFTY",
            strike=25000,
            option_type="CE",
        )
        print("NIFTY contract", c_nf.as_dict())
        q, lots, ls = exchange_qty(lots=2, lot_size=c_nf.lot_size)
        print("NIFTY qty", q, "lots", lots, "lot_size", ls)
    except Exception as e:
        print("NIFTY resolve FAIL", e)
        return 1

    # shadow writeback smoke
    bn = books.bn_book(Path(r"D:\Options-Edge-Lab"), "config/rungs/bn_alpha.yaml")
    order = {
        "client_order_id": "smoke-test",
        "side": "BUY",
        "lots": 1,
        "quantity": q,
        "mode": "paper",
        "state": "simulated",
    }
    wb = shadow_oms.record_broker_order(
        bn,
        day="2026-05-20",
        sleeve="fade",
        order=order,
        contract=c_bn.as_dict(),
    )
    print("shadow_writeback", wb.get("ok"), wb.get("path"))
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
