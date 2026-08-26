"""Pre-aggregated cost-honesty summary (no raw trade CSV to browser)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

COST_MD_REL = Path("reports/clean_25pct_cost_verify.md")
COST_MONTHS_REL = Path("reports/clean_25pct_cost_verify_months.csv")
PRIMARY_VARIANT = "clean_25pct_2l"


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def cost_honesty_payload(
    *,
    nifty_root: Path,
    bn_root: Path,
    underlying: Optional[str] = None,
) -> Dict[str, Any]:
    want = (underlying or "BANKNIFTY").strip().upper()
    if want == "NIFTY":
        return {
            "underlying": "NIFTY",
            "available": False,
            "variant": None,
            "summary": None,
            "months": [],
            "source_path": None,
            "note": "Cost-honesty pack is BANKNIFTY-only in labs today.",
            "errors": [],
        }
    if want != "BANKNIFTY":
        return {
            "underlying": want,
            "available": False,
            "variant": None,
            "summary": None,
            "months": [],
            "source_path": None,
            "errors": [f"invalid_underlying:{want}"],
        }
    root = Path(bn_root)
    months_path = root / COST_MONTHS_REL
    md_path = root / COST_MD_REL
    if not months_path.exists():
        return {
            "underlying": "BANKNIFTY",
            "available": False,
            "variant": PRIMARY_VARIANT,
            "summary": None,
            "months": [],
            "source_path": str(COST_MONTHS_REL).replace("\\", "/"),
            "errors": ["BANKNIFTY:cost_months missing"],
        }
    rows: List[Dict[str, Any]] = []
    try:
        with months_path.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("variant") or "") != PRIMARY_VARIANT:
                    continue
                rows.append(r)
    except OSError as exc:
        return {
            "underlying": "BANKNIFTY",
            "available": False,
            "variant": PRIMARY_VARIANT,
            "summary": None,
            "months": [],
            "source_path": str(COST_MONTHS_REL).replace("\\", "/"),
            "errors": [f"BANKNIFTY:cost_months read_error:{exc}"],
        }
    months_out: List[Dict[str, Any]] = []
    tot_trades = 0
    tot_net = 0.0
    tot_drag = 0.0
    tot_fo = 0.0
    tot_spread = 0.0
    for r in rows:
        n = _i(r.get("n_trades"))
        net = _f(r.get("month_net_pnl")) or 0.0
        drag = _f(r.get("sum_explained_drag")) or 0.0
        fo = _f(r.get("sum_fo_cost")) or 0.0
        spread = _f(r.get("sum_est_spread")) or 0.0
        tot_trades += n
        tot_net += net
        tot_drag += drag
        tot_fo += fo
        tot_spread += spread
        months_out.append(
            {
                "ym": r.get("ym"),
                "n_trades": n,
                "month_net_pnl": net,
                "explained_drag": drag,
                "fo_cost": fo,
                "est_spread": spread,
                "dd_pct": _f(r.get("dd_pct")),
                "lot_size_used": _i(r.get("lot_size_used")) or None,
            }
        )
    # Cap months in API (last 24) — full span still in summary totals
    months_cap = months_out[-24:] if len(months_out) > 24 else months_out
    avg_drag = round(tot_drag / tot_trades, 2) if tot_trades else None
    summary = {
        "n_months": len(months_out),
        "n_trades": tot_trades,
        "net_pnl": round(tot_net, 2),
        "explained_drag": round(tot_drag, 2),
        "fo_cost": round(tot_fo, 2),
        "est_spread": round(tot_spread, 2),
        "avg_explained_drag_per_trade": avg_drag,
        "method": (
            "Est. spread 0.5% mid + India F&O (₹20×2×lots + STT/exch/stamp/SEBI/GST) "
            "vs old ₹40×lots brokerage; explained_drag = spread + (FO − old)."
        ),
        "md_exists": md_path.exists(),
    }
    return {
        "underlying": "BANKNIFTY",
        "available": True,
        "variant": PRIMARY_VARIANT,
        "summary": summary,
        "months": months_cap,
        "months_truncated": len(months_out) > 24,
        "source_path": str(COST_MONTHS_REL).replace("\\", "/"),
        "errors": [],
    }
