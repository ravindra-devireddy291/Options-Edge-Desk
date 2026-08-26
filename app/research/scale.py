"""Capital-scale AUM table from BN scale JSON (no raw trades)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SCALE_REL = Path("reports/clean_25pct_gap300_scale.json")


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def scale_payload(
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
            "span": None,
            "rows": [],
            "source_path": None,
            "note": "Capital-scale pack is BANKNIFTY-only in labs today.",
            "errors": [],
        }
    if want != "BANKNIFTY":
        return {
            "underlying": want,
            "available": False,
            "span": None,
            "rows": [],
            "source_path": None,
            "errors": [f"invalid_underlying:{want}"],
        }
    path = Path(bn_root) / SCALE_REL
    if not path.exists():
        return {
            "underlying": "BANKNIFTY",
            "available": False,
            "span": None,
            "rows": [],
            "source_path": str(SCALE_REL).replace("\\", "/"),
            "errors": ["BANKNIFTY:scale file missing"],
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "underlying": "BANKNIFTY",
            "available": False,
            "span": None,
            "rows": [],
            "source_path": str(SCALE_REL).replace("\\", "/"),
            "errors": [f"BANKNIFTY:scale read_error:{exc}"],
        }
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    runs = raw.get("runs") if isinstance(raw.get("runs"), list) else []
    rows: List[Dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        inv = run.get("investor") if isinstance(run.get("investor"), dict) else {}
        summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
        aum = inv.get("AUM", run.get("capital"))
        deploy = inv.get("deploy_pct")
        if deploy is None and run.get("max_premium_frac") is not None:
            try:
                deploy = 100.0 * float(run["max_premium_frac"])
            except (TypeError, ValueError):
                deploy = None
        rows.append(
            {
                "id": run.get("id"),
                "aum": _f(aum),
                "deploy_pct": _f(deploy),
                "premium_budget": _f(inv.get("premium_budget") or run.get("premium_budget")),
                "return_pct": _f(inv.get("return_pct") or summary.get("return_pct")),
                "peak_dd_pct": _f(inv.get("peak_dd_pct") or summary.get("peak_dd_pct") or summary.get("max_dd_pct")),
                "net_pnl": _f(inv.get("net_pnl") or summary.get("net_pnl")),
                "n_trades": int(inv.get("n_trades") or summary.get("n_trades") or 0),
                "green_pct": _f(inv.get("green_pct")),
            }
        )
    rows.sort(key=lambda r: (r.get("aum") is None, r.get("aum") or 0))
    return {
        "underlying": "BANKNIFTY",
        "available": True,
        "span": meta.get("span"),
        "recipe": meta.get("recipe"),
        "rows": rows,
        "source_path": str(SCALE_REL).replace("\\", "/"),
        "errors": [] if rows else ["BANKNIFTY:scale empty runs"],
    }
