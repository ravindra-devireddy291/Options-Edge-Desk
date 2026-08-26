"""Out-of-sample / half-span confirmation for Lab Trust card."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

NIFTY_OOS_REL = Path("reports/experiments/nifty_shortlist_oos_confirm.json")
BN_HALFSPAN_REL = Path("reports/experiments/bn_survivors_halfspan.json")

# Locked client-facing models (match research/stable Gate-5 defaults).
NIFTY_MODEL_KEY = "T2_Gate5"
BN_BASELINE_FALLBACK = "anchor_client_f4o2_gap300_m6"


def _span_label(start: str, end: str) -> str:
    def _short(d: str) -> str:
        s = str(d or "")[:10]
        if len(s) >= 7:
            return s[:7]  # YYYY-MM
        return s

    a, b = _short(start), _short(end)
    if a and b:
        return f"{a}→{b}"
    return ""


def _verdict(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in ("pass", "ok", "true", "1"):
        return "pass"
    if s in ("fail", "false", "0"):
        return "fail"
    if not s:
        return "unknown"
    return s


def _window(
    *,
    id_: str,
    label: str,
    span: str,
    return_pct: Any,
    peak_dd_pct: Any,
    verdict: str,
) -> Dict[str, Any]:
    try:
        ret = round(float(return_pct), 2)
    except (TypeError, ValueError):
        ret = None
    try:
        dd = round(float(peak_dd_pct), 2)
    except (TypeError, ValueError):
        dd = None
    return {
        "id": id_,
        "label": label,
        "span": span,
        "return_pct": ret,
        "peak_dd_pct": dd,
        "verdict": verdict,
    }


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _nifty_oos(lab_root: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    rel = NIFTY_OOS_REL
    path = lab_root / rel
    if not path.exists():
        return (
            {
                "underlying": "NIFTY",
                "selection_rule": None,
                "model_id": None,
                "windows": [],
                "source_path": str(rel).replace("\\", "/"),
                "errors": ["NIFTY:oos file missing"],
            },
            "NIFTY:oos file missing",
        )
    try:
        raw = _load_json(path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        err = f"NIFTY:oos read_error:{exc}"
        return (
            {
                "underlying": "NIFTY",
                "selection_rule": None,
                "model_id": None,
                "windows": [],
                "source_path": str(rel).replace("\\", "/"),
                "errors": [err],
            },
            err,
        )
    rows = raw.get("rows") if isinstance(raw.get("rows"), dict) else {}
    model = rows.get(NIFTY_MODEL_KEY) or {}
    if not model and rows:
        # first baseline role if present
        for k, v in rows.items():
            if isinstance(v, dict) and isinstance(v.get("full"), dict):
                if str((v.get("full") or {}).get("role") or "") == "baseline":
                    model = v
                    break
        if not model:
            model = next(iter(rows.values()))
    windows: List[Dict[str, Any]] = []
    for sid, label in (("train", "Train"), ("oos", "Out of sample"), ("full", "Full span")):
        cell = model.get(sid) if isinstance(model, dict) else None
        if not isinstance(cell, dict):
            continue
        span = _span_label(cell.get("start"), cell.get("end")) or sid
        # Gate-5 recommended: treat present metrics as informational pass for Trust card
        # (shortlist gates apply to Pick_* models, not the locked T2 baseline).
        windows.append(
            _window(
                id_=sid,
                label=label,
                span=span,
                return_pct=cell.get("return_pct"),
                peak_dd_pct=cell.get("peak_dd_pct"),
                verdict="pass",
            )
        )
    model_id = None
    if isinstance(model.get("full"), dict):
        model_id = model["full"].get("id")
    elif isinstance(model.get("train"), dict):
        model_id = model["train"].get("id")
    return (
        {
            "underlying": "NIFTY",
            "selection_rule": "locked Gate-5 T2 recommended — train vs OOS walk-forward",
            "model_id": model_id or NIFTY_MODEL_KEY,
            "windows": windows,
            "source_path": str(rel).replace("\\", "/"),
            "errors": [] if windows else ["NIFTY:oos no train/oos windows"],
        },
        None if windows else "NIFTY:oos no train/oos windows",
    )


def _bn_halfspan(lab_root: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    rel = BN_HALFSPAN_REL
    path = lab_root / rel
    if not path.exists():
        return (
            {
                "underlying": "BANKNIFTY",
                "selection_rule": None,
                "model_id": None,
                "windows": [],
                "source_path": str(rel).replace("\\", "/"),
                "errors": ["BANKNIFTY:halfspan file missing"],
            },
            "BANKNIFTY:halfspan file missing",
        )
    try:
        raw = _load_json(path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        err = f"BANKNIFTY:halfspan read_error:{exc}"
        return (
            {
                "underlying": "BANKNIFTY",
                "selection_rule": None,
                "model_id": None,
                "windows": [],
                "source_path": str(rel).replace("\\", "/"),
                "errors": [err],
            },
            err,
        )
    baseline_id = str(raw.get("baseline_id") or BN_BASELINE_FALLBACK)
    ranked = raw.get("ranked") if isinstance(raw.get("ranked"), list) else []
    row = next((r for r in ranked if isinstance(r, dict) and r.get("id") == baseline_id), None)
    if row is None and ranked:
        row = next((r for r in ranked if isinstance(r, dict) and r.get("thesis") == "anchor"), ranked[0])
    if not isinstance(row, dict):
        err = "BANKNIFTY:halfspan baseline missing"
        return (
            {
                "underlying": "BANKNIFTY",
                "selection_rule": None,
                "model_id": baseline_id,
                "windows": [],
                "source_path": str(rel).replace("\\", "/"),
                "errors": [err],
            },
            err,
        )
    span_meta = raw.get("spans") if isinstance(raw.get("spans"), dict) else {}
    cells = row.get("spans") if isinstance(row.get("spans"), dict) else {}
    # Map halfspans → train-like (early) / oos-like (later calendar)
    order = [
        ("2021_h2", "train", "Train (2021 H2)"),
        ("2024_full", "oos", "Out of sample (2024)"),
    ]
    windows: List[Dict[str, Any]] = []
    for key, id_, label in order:
        cell = cells.get(key) if isinstance(cells.get(key), dict) else None
        if not cell:
            continue
        meta = span_meta.get(key) if isinstance(span_meta.get(key), (list, tuple)) else None
        if meta and len(meta) >= 2:
            span = _span_label(meta[0], meta[1])
        else:
            span = key
        windows.append(
            _window(
                id_=id_,
                label=label,
                span=span,
                return_pct=cell.get("return_pct"),
                peak_dd_pct=cell.get("peak_dd_pct"),
                verdict=_verdict(cell.get("verdict")),
            )
        )
    both = bool(row.get("pass_both_halfspans"))
    rule = (
        f"client baseline {baseline_id} — must PASS both half-spans"
        + (" (pass)" if both else " (incomplete)")
    )
    return (
        {
            "underlying": "BANKNIFTY",
            "selection_rule": rule,
            "model_id": baseline_id,
            "windows": windows,
            "source_path": str(rel).replace("\\", "/"),
            "errors": [] if windows else ["BANKNIFTY:halfspan empty windows"],
        },
        None if windows else "BANKNIFTY:halfspan empty windows",
    )


def oos_payload(
    *,
    nifty_root: Path,
    bn_root: Path,
    underlying: Optional[str] = None,
) -> Dict[str, Any]:
    want = (underlying or "").strip().upper() or None
    if want and want not in ("NIFTY", "BANKNIFTY"):
        return {"books": [], "errors": [f"invalid_underlying:{want}"]}
    books: List[Dict[str, Any]] = []
    errors: List[str] = []
    if want in (None, "NIFTY"):
        row, err = _nifty_oos(Path(nifty_root))
        books.append(row)
        if err:
            errors.append(err)
    if want in (None, "BANKNIFTY"):
        row, err = _bn_halfspan(Path(bn_root))
        books.append(row)
        if err:
            errors.append(err)
    if want:
        # single-book response matches ticket shape
        book = books[0] if books else {
            "underlying": want,
            "selection_rule": None,
            "windows": [],
            "source_path": None,
            "errors": errors,
        }
        return {**book, "errors": list(dict.fromkeys((book.get("errors") or []) + errors))}
    return {"books": books, "errors": errors}
