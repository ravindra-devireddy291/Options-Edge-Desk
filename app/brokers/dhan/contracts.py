"""Resolve NSE F&O option contracts (security_id + lot_size) for NIFTY / BANKNIFTY."""
from __future__ import annotations

import csv
import io
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"
CACHE_PATH = CACHE_DIR / "dhan_scrip_master_detailed.csv"
CACHE_MAX_AGE_SEC = 12 * 3600

# Fallback lot sizes if master row missing (NSE current defaults)
DEFAULT_LOT = {"NIFTY": 65, "BANKNIFTY": 30}


@dataclass
class Contract:
    underlying: str
    security_id: str
    tradingsymbol: str
    strike: float
    option_type: str  # CE / PE
    expiry: str  # YYYY-MM-DD
    lot_size: int
    lot_from_master: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "underlying": self.underlying,
            "security_id": self.security_id,
            "tradingsymbol": self.tradingsymbol,
            "strike": self.strike,
            "option_type": self.option_type,
            "expiry": self.expiry,
            "lot_size": self.lot_size,
            "lot_from_master": self.lot_from_master,
        }


_MASTER_ROWS: Optional[List[Dict[str, str]]] = None
_MASTER_LOADED_AT = 0.0


def _ensure_master(*, force: bool = False) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stale = (
        force
        or not CACHE_PATH.exists()
        or (time.time() - CACHE_PATH.stat().st_mtime) > CACHE_MAX_AGE_SEC
    )
    if stale:
        req = urllib.request.Request(SCRIP_MASTER_URL, method="GET")
        with urllib.request.urlopen(req, timeout=120) as resp:
            CACHE_PATH.write_bytes(resp.read())
    return CACHE_PATH


def _load_master(*, force: bool = False) -> List[Dict[str, str]]:
    global _MASTER_ROWS, _MASTER_LOADED_AT
    path = _ensure_master(force=force)
    if (
        _MASTER_ROWS is not None
        and not force
        and (time.time() - _MASTER_LOADED_AT) < CACHE_MAX_AGE_SEC
    ):
        return _MASTER_ROWS
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
    _MASTER_ROWS = rows
    _MASTER_LOADED_AT = time.time()
    return rows


def _pick(row: Dict[str, str], *names: str) -> str:
    upper = {k.upper(): v for k, v in row.items()}
    for n in names:
        if n in row and row[n]:
            return row[n]
        if n.upper() in upper and upper[n.upper()]:
            return upper[n.upper()]
    return ""


def _parse_expiry(raw: str) -> Optional[date]:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).date()
    except ValueError:
        return None


def _norm_opt(raw: str) -> str:
    s = (raw or "").upper()
    if s in ("CE", "CALL", "C"):
        return "CE"
    if s in ("PE", "PUT", "P"):
        return "PE"
    return s


def option_rows(underlying: str) -> List[Dict[str, Any]]:
    und = underlying.upper()
    out: List[Dict[str, Any]] = []
    for r in _load_master():
        inst = _pick(r, "SEM_INSTRUMENT_NAME", "INSTRUMENT").upper()
        if inst != "OPTIDX":
            continue
        sym = _pick(
            r,
            "SEM_TRADING_SYMBOL",
            "TRADING_SYMBOL",
            "SEM_CUSTOM_SYMBOL",
            "DISPLAY_NAME",
            "SYMBOL_NAME",
        )
        under = _pick(r, "UNDERLYING_SYMBOL", "SEM_UNDERLYING", "SEM_CUSTOM_SYMBOL").upper()
        if und not in sym.upper() and und not in under:
            continue
        # avoid BANKNIFTY when looking for NIFTY
        if und == "NIFTY" and "BANKNIFTY" in sym.upper():
            continue
        sid = _pick(r, "SEM_SMST_SECURITY_ID", "SECURITY_ID")
        if not sid:
            continue
        strike_s = _pick(r, "SEM_STRIKE_PRICE", "STRIKE_PRICE")
        try:
            strike = float(strike_s)
        except ValueError:
            continue
        opt = _norm_opt(_pick(r, "SEM_OPTION_TYPE", "OPTION_TYPE"))
        exp = _parse_expiry(_pick(r, "SEM_EXPIRY_DATE", "SM_EXPIRY_DATE", "EXPIRY_DATE"))
        if not exp or opt not in ("CE", "PE"):
            continue
        lot_s = _pick(r, "SEM_LOT_UNITS", "LOT_SIZE", "SEM_LOT_SIZE")
        lot_from_master = bool(lot_s)
        try:
            lot = int(float(lot_s)) if lot_s else int(DEFAULT_LOT.get(und, 1))
        except ValueError:
            lot = int(DEFAULT_LOT.get(und, 1))
            lot_from_master = False
        out.append(
            {
                "security_id": str(sid),
                "tradingsymbol": sym,
                "strike": strike,
                "option_type": opt,
                "expiry": exp,
                "lot_size": max(1, lot),
                "lot_from_master": lot_from_master,
                "underlying": und,
            }
        )
    return out


def _is_exchange_symbol(symbol: str) -> bool:
    """Lake rows use BANKNIFTY-Oct2026-57400-CE; Dhan master uses SEM_TRADING_SYMBOL."""
    s = (symbol or "").strip()
    if not s:
        return False
    if s.endswith("-FADE") or s.endswith("-ORB"):
        return False
    parts = s.split("-")
    if len(parts) >= 3:
        return False
    return True


def resolve_by_symbol(symbol: str, underlying: Optional[str] = None) -> Optional[Contract]:
    if not _is_exchange_symbol(symbol or ""):
        return None
    sym = (symbol or "").strip().upper()
    und = (underlying or ("BANKNIFTY" if "BANKNIFTY" in sym else "NIFTY")).upper()
    for r in option_rows(und):
        if r["tradingsymbol"].upper() == sym or sym in r["tradingsymbol"].upper():
            return Contract(
                underlying=und,
                security_id=str(r["security_id"]),
                tradingsymbol=str(r["tradingsymbol"]),
                strike=float(r["strike"]),
                option_type=str(r["option_type"]),
                expiry=r["expiry"].isoformat(),
                lot_size=int(r["lot_size"]),
                lot_from_master=bool(r.get("lot_from_master", True)),
            )
    return None


def resolve_contract(
    *,
    underlying: str,
    strike: Optional[float] = None,
    option_type: Optional[str] = None,
    symbol: Optional[str] = None,
    security_id: Optional[str] = None,
    expiry: Optional[str] = None,
    session_day: Optional[date] = None,
) -> Contract:
    und = underlying.upper()
    if security_id and str(security_id) not in ("", "0"):
        # enrich from master if possible
        for r in option_rows(und):
            if str(r["security_id"]) == str(security_id):
                return Contract(
                    underlying=und,
                    security_id=str(r["security_id"]),
                    tradingsymbol=str(r["tradingsymbol"]),
                    strike=float(r["strike"]),
                    option_type=str(r["option_type"]),
                    expiry=r["expiry"].isoformat(),
                    lot_size=int(r["lot_size"]),
                    lot_from_master=bool(r.get("lot_from_master", True)),
                )
        return Contract(
            underlying=und,
            security_id=str(security_id),
            tradingsymbol=symbol or "",
            strike=float(strike or 0),
            option_type=_norm_opt(option_type or ""),
            expiry=expiry or "",
            lot_size=int(DEFAULT_LOT.get(und, 1)),
            lot_from_master=False,
        )

    if symbol and _is_exchange_symbol(symbol):
        hit = resolve_by_symbol(symbol, und)
        if hit:
            return hit

    opt = _norm_opt(option_type or "")
    if strike is None or opt not in ("CE", "PE"):
        raise RuntimeError(
            "Cannot resolve contract: need security_id, or trading symbol, "
            "or underlying+strike+CE/PE"
        )

    day = session_day or date.today()
    exp_filter: Optional[date] = _parse_expiry(expiry) if expiry else None
    if exp_filter and exp_filter == day:
        # Journal/auto used to pass session day as expiry; that is not an option expiry.
        exp_filter = None

    def _candidates(*, refresh: bool) -> List[Dict[str, Any]]:
        if refresh:
            _load_master(force=True)
        found = [
            r
            for r in option_rows(und)
            if abs(float(r["strike"]) - float(strike)) < 0.01
            and r["option_type"] == opt
            and r["expiry"] >= day
        ]
        if exp_filter:
            found = [r for r in found if r["expiry"] == exp_filter]
        return found

    candidates = _candidates(refresh=False)
    if not candidates:
        candidates = _candidates(refresh=True)
    if not candidates:
        step = 100.0 if und == "BANKNIFTY" else 50.0
        nearby = [
            r
            for r in option_rows(und)
            if r["option_type"] == opt
            and r["expiry"] >= day
            and abs(float(r["strike"]) - float(strike)) <= step * 2
        ]
        if exp_filter:
            nearby = [r for r in nearby if r["expiry"] == exp_filter]
        nearby.sort(key=lambda r: (abs(float(r["strike"]) - float(strike)), r["expiry"]))
        candidates = nearby[:1]
    if not candidates:
        raise RuntimeError(
            f"No live {und} {strike} {opt} contract in scrip master for >= {day}"
        )
    candidates.sort(key=lambda r: (abs(float(r["strike"]) - float(strike)), r["expiry"]))
    r = candidates[0]
    return Contract(
        underlying=und,
        security_id=str(r["security_id"]),
        tradingsymbol=str(r["tradingsymbol"]),
        strike=float(r["strike"]),
        option_type=str(r["option_type"]),
        expiry=r["expiry"].isoformat(),
        lot_size=int(r["lot_size"]),
        lot_from_master=bool(r.get("lot_from_master", True)),
    )


def exchange_qty(
    *,
    lots: Optional[int] = None,
    lot_size: int,
    quantity: Optional[int] = None,
    prefer_lots: bool = True,
) -> Tuple[int, int, int]:
    """Return (exchange_qty, lots, lot_size). If lots is set, ignore quantity."""
    ls = max(1, int(lot_size))
    if prefer_lots and lots is not None:
        lots_i = max(1, int(lots))
        return lots_i * ls, lots_i, ls
    if quantity is not None and int(quantity) > 0:
        q = int(quantity)
        if q % ls != 0:
            if q <= 50:
                lots_i = q
                return lots_i * ls, lots_i, ls
            raise RuntimeError(f"quantity {q} not a multiple of lot_size {ls}")
        return q, q // ls, ls
    lots_i = max(1, int(lots or 1))
    return lots_i * ls, lots_i, ls


def lookup_by_security_id(security_id: str, underlying: Optional[str] = None) -> Optional[Contract]:
    sid = str(security_id or "").strip()
    if not sid:
        return None
    unders = [underlying.upper()] if underlying else ["NIFTY", "BANKNIFTY"]
    for und in unders:
        try:
            for r in option_rows(und):
                if str(r["security_id"]) == sid:
                    return Contract(
                        underlying=und,
                        security_id=str(r["security_id"]),
                        tradingsymbol=str(r["tradingsymbol"]),
                        strike=float(r["strike"]),
                        option_type=str(r["option_type"]),
                        expiry=r["expiry"].isoformat(),
                        lot_size=int(r["lot_size"]),
                        lot_from_master=bool(r.get("lot_from_master", True)),
                    )
        except Exception:
            continue
    return None


def default_lot_size(underlying: str) -> int:
    return int(DEFAULT_LOT.get(underlying.upper(), 1))


def chain_snapshot(
    *,
    underlying: str,
    expiry: Optional[str] = None,
    spot: Optional[float] = None,
    session_day: Optional[date] = None,
    wing: int = 6,
) -> Dict[str, Any]:
    """ATM ± a handful of strikes for the Order chip row."""
    und = underlying.upper()
    day = session_day or date.today()
    rows = option_rows(und)
    live = [r for r in rows if r["expiry"] >= day]
    expiries = sorted({r["expiry"].isoformat() for r in live})
    exp_d = _parse_expiry(expiry) if expiry else None
    if exp_d is None and expiries:
        exp_d = _parse_expiry(expiries[0])
    chosen = [r for r in live if exp_d and r["expiry"] == exp_d]
    if not chosen and live:
        exp_d = live[0]["expiry"]
        chosen = [r for r in live if r["expiry"] == exp_d]
    lot = int(chosen[0]["lot_size"]) if chosen else int(DEFAULT_LOT.get(und, 1))
    strikes = sorted({float(r["strike"]) for r in chosen})
    step = 50.0
    if len(strikes) >= 2:
        diffs = sorted(b - a for a, b in zip(strikes, strikes[1:]) if b > a)
        if diffs:
            step = float(diffs[0])
    atm = None
    if strikes:
        ref = float(spot) if spot not in (None, 0) else strikes[len(strikes) // 2]
        atm = min(strikes, key=lambda s: abs(s - ref))
        try:
            idx = strikes.index(atm)
        except ValueError:
            idx = len(strikes) // 2
        lo = max(0, idx - wing)
        hi = min(len(strikes), idx + wing + 1)
        window = strikes[lo:hi]
        if len(window) < 5 and len(strikes) >= 5:
            window = strikes[:5] if idx < 5 else strikes[-5:]
        strikes = window
    return {
        "underlying": und,
        "spot": spot,
        "lot_size": lot,
        "expiry": exp_d.isoformat() if exp_d else None,
        "expiries": expiries,
        "atm_strike": atm,
        "strike_step": step,
        "strikes": strikes,
    }
