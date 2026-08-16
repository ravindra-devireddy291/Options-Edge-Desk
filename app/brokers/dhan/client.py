"""Dhan HQ v2 broker adapter (read + gated write) for Options Edge Desk."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

API_BASE = "https://api.dhan.co/v2"
AUTH_BASE = "https://auth.dhan.co"
NIFTY_SECURITY_ID = "13"
BN_SECURITY_ID = "25"
SEGMENT_INDEX = "IDX_I"
SEGMENT_OPT = "NSE_FNO"

_BROKER_HEALTH: Dict[str, Any] = {"ok": True, "detail": None}


def mark_broker(ok: bool, detail: Optional[str] = None) -> None:
    _BROKER_HEALTH["ok"] = bool(ok)
    _BROKER_HEALTH["detail"] = None if ok else (detail or "broker unreachable")


def broker_reachable() -> bool:
    return bool(_BROKER_HEALTH.get("ok"))


def desk_env_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".env"


def load_dotenv(path: Optional[Path] = None) -> None:
    env_path = path or desk_env_path()
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if not k:
            continue
        cur = os.environ.get(k)
        # Empty bash leftovers must not block a real value from .env (JWT tokens).
        if cur is None or (not cur and v):
            os.environ[k] = v


def persist_env_vars(updates: Dict[str, str], path: Optional[Path] = None) -> Path:
    """Upsert keys into desk .env so restarts keep the token."""
    env_path = path or desk_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    vals: Dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    vals.update({k: str(v) for k, v in updates.items() if v is not None})
    env_path.write_text("\n".join(f"{k}={v}" for k, v in vals.items()) + "\n", encoding="utf-8")
    return env_path


def set_access_token(token: str, client_id: Optional[str] = None, *, persist: bool = True) -> None:
    token = (token or "").strip()
    if not token:
        raise RuntimeError("empty access token")
    os.environ["DHAN_ACCESS_TOKEN"] = token
    if client_id:
        os.environ["DHAN_CLIENT_ID"] = str(client_id).strip()
    elif not os.environ.get("DHAN_CLIENT_ID"):
        try:
            os.environ["DHAN_CLIENT_ID"] = jwt_client_id(token) or ""
        except Exception:
            pass
    if persist:
        upd = {"DHAN_ACCESS_TOKEN": token}
        cid = os.environ.get("DHAN_CLIENT_ID") or ""
        if cid:
            upd["DHAN_CLIENT_ID"] = cid
        persist_env_vars(upd)


def jwt_payload(token: str) -> Dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    pad = "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(parts[1] + pad))
    except Exception:
        return {}


def jwt_client_id(token: str) -> Optional[str]:
    data = jwt_payload(token)
    cid = data.get("dhanClientId") or data.get("clientId")
    return str(cid) if cid else None


def jwt_exp_unix(token: str) -> Optional[int]:
    data = jwt_payload(token)
    exp = data.get("exp")
    try:
        return int(exp) if exp is not None else None
    except (TypeError, ValueError):
        return None


def credentials() -> Tuple[str, str]:
    token = os.environ.get("DHAN_ACCESS_TOKEN") or os.environ.get("DHAN_TOKEN") or ""
    client = os.environ.get("DHAN_CLIENT_ID") or ""
    if not token:
        raise RuntimeError("DHAN_ACCESS_TOKEN missing")
    if not client:
        client = jwt_client_id(token) or ""
        if not client:
            raise RuntimeError("DHAN_CLIENT_ID missing")
        os.environ["DHAN_CLIENT_ID"] = client
    return client, token


def _totp_code(secret: str, for_time: Optional[int] = None) -> str:
    """RFC 6238 TOTP (6 digits / 30s). Accepts base32 secret."""
    key = secret.strip().replace(" ", "").upper()
    # pad base32
    key += "=" * ((8 - len(key) % 8) % 8)
    raw = base64.b32decode(key, casefold=True)
    counter = int((for_time if for_time is not None else time.time()) // 30)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(raw, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def renew_access_token(*, persist: bool = True) -> Dict[str, Any]:
    """Renew still-valid web token via Dhan RenewToken (extends ~24h)."""
    client, token = credentials()
    url = f"{API_BASE}/RenewToken"
    headers = {
        "access-token": token,
        "dhanClientId": client,
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", "replace")
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"RenewToken HTTP {e.code}: {err}") from e
    new_token = str(data.get("accessToken") or data.get("access_token") or "")
    if not new_token:
        raise RuntimeError(f"RenewToken missing accessToken: {data}")
    set_access_token(new_token, str(data.get("dhanClientId") or client), persist=persist)
    return {"ok": True, "method": "renew", "expiryTime": data.get("expiryTime"), "raw_keys": list(data.keys())}


def generate_access_token_totp(*, persist: bool = True) -> Dict[str, Any]:
    """Generate a fresh 24h token using DHAN_PIN + DHAN_TOTP_SECRET (no browser)."""
    client = os.environ.get("DHAN_CLIENT_ID") or ""
    pin = os.environ.get("DHAN_PIN") or ""
    secret = os.environ.get("DHAN_TOTP_SECRET") or ""
    if not client or not pin or not secret:
        raise RuntimeError("DHAN_CLIENT_ID, DHAN_PIN, and DHAN_TOTP_SECRET required for TOTP login")
    totp = _totp_code(secret)
    qs = urllib.parse.urlencode({"dhanClientId": client, "pin": pin, "totp": totp})
    url = f"{AUTH_BASE}/app/generateAccessToken?{qs}"
    req = urllib.request.Request(url, method="POST", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", "replace")
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"generateAccessToken HTTP {e.code}: {err}") from e
    new_token = str(data.get("accessToken") or "")
    if not new_token:
        raise RuntimeError(f"generateAccessToken missing accessToken: {data}")
    set_access_token(new_token, str(data.get("dhanClientId") or client), persist=persist)
    return {"ok": True, "method": "totp", "expiryTime": data.get("expiryTime")}


def ensure_fresh_token(*, renew_if_within_sec: int = 6 * 3600, persist: bool = True) -> Dict[str, Any]:
    """
    Keep token alive:
    1) If JWT still valid and within renew window → RenewToken
    2) Else if TOTP secrets configured → generateAccessToken
    3) Else report needs_manual
    """
    token = os.environ.get("DHAN_ACCESS_TOKEN") or ""
    now = int(time.time())
    exp = jwt_exp_unix(token) if token else None
    seconds_left = (exp - now) if exp else None

    if token and seconds_left is not None and seconds_left > renew_if_within_sec:
        return {
            "ok": True,
            "action": "none",
            "seconds_left": seconds_left,
            "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    if token and seconds_left is not None and seconds_left > 60:
        try:
            renewed = renew_access_token(persist=persist)
            exp2 = jwt_exp_unix(os.environ.get("DHAN_ACCESS_TOKEN") or "")
            return {
                **renewed,
                "action": "renewed",
                "seconds_left": (exp2 - now) if exp2 else None,
                "expires_at": datetime.fromtimestamp(exp2, tz=timezone.utc).isoformat().replace("+00:00", "Z")
                if exp2
                else None,
            }
        except Exception as renew_exc:  # noqa: BLE001
            # fall through to TOTP if available
            renew_err = str(renew_exc)
    else:
        renew_err = "token missing or expired"

    if os.environ.get("DHAN_TOTP_SECRET") and os.environ.get("DHAN_PIN"):
        try:
            gen = generate_access_token_totp(persist=persist)
            exp2 = jwt_exp_unix(os.environ.get("DHAN_ACCESS_TOKEN") or "")
            return {
                **gen,
                "action": "generated_totp",
                "seconds_left": (exp2 - int(time.time())) if exp2 else None,
                "prior_renew_error": renew_err,
            }
        except Exception as totp_exc:  # noqa: BLE001
            return {
                "ok": False,
                "action": "needs_manual",
                "detail": f"renew failed ({renew_err}); totp failed ({totp_exc})",
                "seconds_left": seconds_left,
            }

    return {
        "ok": False,
        "action": "needs_manual",
        "detail": renew_err,
        "seconds_left": seconds_left,
        "hint": "Paste a fresh web token once, or set DHAN_PIN + DHAN_TOTP_SECRET for unattended daily login",
    }


def token_status() -> Dict[str, Any]:
    token = os.environ.get("DHAN_ACCESS_TOKEN") or ""
    client = os.environ.get("DHAN_CLIENT_ID") or (jwt_client_id(token) if token else "") or ""
    exp = jwt_exp_unix(token) if token else None
    now = int(time.time())
    seconds_left = (exp - now) if exp else None
    expires_at = (
        datetime.fromtimestamp(exp, tz=timezone.utc).isoformat().replace("+00:00", "Z") if exp else None
    )
    auto_totp = bool(os.environ.get("DHAN_TOTP_SECRET") and os.environ.get("DHAN_PIN") and client)
    base = {
        "api_key": client,
        "login_url": "https://web.dhan.co/",
        "has_access_token": bool(token),
        "access_token_masked": (token[:4] + "••••••••") if len(token) >= 4 else None,
        "broker": "dhan",
        "expires_at": expires_at,
        "seconds_left": seconds_left,
        "auto_renew_enabled": True,
        "auto_totp_enabled": auto_totp,
    }
    if not token:
        return {**base, "token_ok": False, "detail": "DHAN_ACCESS_TOKEN missing"}
    try:
        _request("GET", "/fundlimit", retries=1, sleep_s=0.05)
        return {**base, "token_ok": True}
    except Exception as exc:  # noqa: BLE001
        return {**base, "token_ok": False, "detail": str(exc)}


def _request(
    method: str,
    path: str,
    body: Optional[dict] = None,
    *,
    retries: int = 3,
    sleep_s: float = 0.25,
) -> Any:
    client, token = credentials()
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "access-token": token,
        "client-id": client,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8", "replace")
                if not raw:
                    mark_broker(True)
                    return {}
                out = json.loads(raw)
                if sleep_s:
                    time.sleep(sleep_s)
                mark_broker(True)
                return out
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "replace")
            last_err = RuntimeError(f"HTTP {e.code}: {err_body}")
            if e.code in (401, 403):
                mark_broker(False, str(last_err))
            elif e.code >= 500:
                mark_broker(False, str(last_err))
            if e.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise last_err from e
        except Exception as e:  # noqa: BLE001
            last_err = e
            mark_broker(False, str(e))
            if attempt + 1 < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise
    mark_broker(False, str(last_err) if last_err else "request failed")
    raise last_err or RuntimeError("request failed")


def _as_list(raw: Any) -> List[dict]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for k in ("positions", "orders", "orderList", "openOrders"):
                if isinstance(data.get(k), list):
                    return [x for x in data[k] if isinstance(x, dict)]
            return [data]
    return []


def fund_limit() -> Dict[str, Any]:
    raw = _request("GET", "/fundlimit", sleep_s=0.1)
    if isinstance(raw, dict):
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        return dict(data or {})
    return {}


def positions() -> List[dict]:
    # Dhan v2 positions endpoint
    for path in ("/positions", "/position"):
        try:
            return _as_list(_request("GET", path, sleep_s=0.15))
        except Exception:
            continue
    return []


def open_orders() -> List[dict]:
    for path in ("/orders", "/orders/open"):
        try:
            rows = _as_list(_request("GET", path, sleep_s=0.15))
            # filter terminal states if present
            out = []
            for r in rows:
                st = str(r.get("orderStatus") or r.get("status") or "").upper()
                if st in ("TRADED", "REJECTED", "CANCELLED", "CANCELED", "EXPIRED"):
                    continue
                out.append(r)
            return out if out or path.endswith("/open") else rows
        except Exception:
            continue
    return []


def trade_book_today() -> List[dict]:
    raw = _request("GET", "/trades", sleep_s=0.15)
    return _as_list(raw)


def trade_history(from_date: str, to_date: str, page: int = 0) -> List[dict]:
    raw = _request("GET", f"/trades/{from_date}/{to_date}/{page}", sleep_s=0.15)
    return _as_list(raw)


def intraday_minute(
    security_id: str,
    *,
    exchange_segment: str,
    instrument: str,
    from_date: str,
    to_date: str,
    interval: int = 1,
) -> Dict[str, Any]:
    return _request(
        "POST",
        "/charts/intraday",
        {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": str(interval),
            "oi": False,
            "fromDate": from_date,
            "toDate": to_date,
        },
        sleep_s=0.1,
    )


def _index_series(security_id: str) -> Tuple[List[float], List[Any]]:
    from datetime import date, timedelta

    end = date.today()
    start = end - timedelta(days=7)
    raw = intraday_minute(
        security_id,
        exchange_segment=SEGMENT_INDEX,
        instrument="INDEX",
        from_date=start.isoformat(),
        to_date=end.isoformat(),
        interval=1,
    )
    if not isinstance(raw, dict):
        return [], []
    closes = raw.get("close") or []
    stamps = raw.get("timestamp") or raw.get("start_Time") or []
    out_c: List[float] = []
    for c in closes:
        try:
            out_c.append(float(c))
        except (TypeError, ValueError):
            continue
    return out_c, list(stamps) if isinstance(stamps, list) else []


def latest_spot(security_id: str) -> Optional[float]:
    """Best-effort last close from today's (or recent) 1m chart."""
    try:
        closes, _ = _index_series(security_id)
    except Exception:
        return None
    return closes[-1] if closes else None


def _change_pct(closes: List[float]) -> Optional[float]:
    if len(closes) < 2:
        return None
    ltp = closes[-1]
    prev = closes[0]
    if len(closes) > 30:
        prev = closes[-31]
    if prev == 0:
        return None
    return round(100.0 * (ltp - prev) / prev, 4)


def spots() -> Dict[str, Optional[float]]:
    pack = spots_with_change()
    n = pack["NIFTY"]["ltp"]
    b = pack["BANKNIFTY"]["ltp"]
    return {"NIFTY": n, "BANKNIFTY": b, "nifty_spot": n, "banknifty_spot": b}


_SPOTS_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}


def spots_with_change() -> Dict[str, Dict[str, Optional[float]]]:
    now = time.time()
    cached = _SPOTS_CACHE.get("data")
    if cached is not None and now - float(_SPOTS_CACHE.get("at") or 0) < 5.0:
        return cached
    out: Dict[str, Dict[str, Optional[float]]] = {
        "NIFTY": {"ltp": None, "change_pct": None},
        "BANKNIFTY": {"ltp": None, "change_pct": None},
    }
    for name, sid in (("NIFTY", NIFTY_SECURITY_ID), ("BANKNIFTY", BN_SECURITY_ID)):
        try:
            closes, _ = _index_series(sid)
        except Exception:
            continue
        if not closes:
            continue
        out[name] = {"ltp": closes[-1], "change_pct": _change_pct(closes)}
    _SPOTS_CACHE["at"] = now
    _SPOTS_CACHE["data"] = out
    return out


def _underlying_from_symbol(sym: str) -> str:
    s = (sym or "").upper()
    if "BANKNIFTY" in s:
        return "BANKNIFTY"
    if "NIFTY" in s:
        return "NIFTY"
    return "UNKNOWN"


def _contract_bits(sym: str, security_id: str, underlying: str) -> Dict[str, Any]:
    from app.brokers.dhan.contracts import default_lot_size, lookup_by_security_id, resolve_by_symbol

    c = lookup_by_security_id(security_id, underlying if underlying in ("NIFTY", "BANKNIFTY") else None)
    if c is None and sym:
        c = resolve_by_symbol(sym, underlying if underlying in ("NIFTY", "BANKNIFTY") else None)
    if c is None:
        und = underlying if underlying in ("NIFTY", "BANKNIFTY") else _underlying_from_symbol(sym)
        return {
            "underlying": und,
            "security_id": str(security_id or ""),
            "expiry": None,
            "strike": None,
            "option_type": None,
            "lot_size": default_lot_size(und) if und in ("NIFTY", "BANKNIFTY") else 1,
        }
    return {
        "underlying": c.underlying,
        "security_id": c.security_id,
        "expiry": c.expiry,
        "strike": c.strike,
        "option_type": c.option_type,
        "lot_size": c.lot_size,
        "tradingsymbol": c.tradingsymbol,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_utc_z(raw: Any) -> Optional[str]:
    if raw is None or raw == "":
        return None
    s = str(raw)
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return s
    return s


def positions_grid() -> Dict[str, Any]:
    rows_out = []
    for p in positions():
        sym = str(
            p.get("tradingSymbol")
            or p.get("tradingsymbol")
            or p.get("securityId")
            or ""
        )
        qty = float(p.get("netQty") or p.get("quantity") or p.get("positionQty") or 0)
        if abs(qty) < 1e-9:
            continue
        sid = str(p.get("securityId") or p.get("security_id") or "")
        und = _underlying_from_symbol(sym)
        bits = _contract_bits(sym, sid, und)
        lot_size = max(1, int(bits.get("lot_size") or 1))
        lots = int(abs(qty) // lot_size) if lot_size else int(abs(qty))
        avg = float(p.get("averagePrice") or p.get("avgPrice") or p.get("costPrice") or 0)
        mark = p.get("ltp") or p.get("lastPrice") or p.get("close")
        try:
            mark_f = float(mark) if mark is not None else None
        except (TypeError, ValueError):
            mark_f = None
        upnl = p.get("unrealizedProfit") or p.get("unrealized_pnl")
        try:
            upnl_f = float(upnl) if upnl is not None else (
                round((mark_f - avg) * qty, 2) if mark_f is not None else None
            )
        except (TypeError, ValueError):
            upnl_f = None
        q_i = int(qty)
        rows_out.append(
            {
                "symbol": bits.get("tradingsymbol") or sym,
                "tradingsymbol": bits.get("tradingsymbol") or sym,
                "underlying": bits.get("underlying") or und,
                "security_id": bits.get("security_id") or sid,
                "expiry": bits.get("expiry"),
                "strike": bits.get("strike"),
                "option_type": bits.get("option_type"),
                "side": "LONG" if q_i > 0 else "SHORT",
                "qty": q_i,
                "quantity": q_i,
                "lots": lots,
                "lot_size": lot_size,
                "average_price": avg,
                "mark_price": mark_f,
                "ltp": mark_f,
                "unrealized_pnl": upnl_f,
                "broker_qty": q_i,
                "shadow_qty": 0,
                "exit_tracked": False,
                "drift_status": "broker_only",
                "exit_profile": None,
            }
        )
    return {
        "rows": rows_out,
        "row_count": len(rows_out),
        "snapshot_at": _utc_now(),
        "detail": None,
    }


def open_orders_response() -> Dict[str, Any]:
    orders = []
    terminal = {"TRADED", "REJECTED", "CANCELLED", "CANCELED", "EXPIRED"}
    for o in open_orders():
        sym = str(o.get("tradingSymbol") or o.get("tradingsymbol") or o.get("securityId") or "")
        oid = str(o.get("orderId") or o.get("brokerOrderId") or "")
        sid = str(o.get("securityId") or o.get("security_id") or "")
        und = _underlying_from_symbol(sym)
        bits = _contract_bits(sym, sid, und)
        lot_size = max(1, int(bits.get("lot_size") or 1))
        qty = int(float(o.get("quantity") or o.get("tradedQuantity") or 0))
        status = str(o.get("orderStatus") or o.get("status") or "")
        st_u = status.upper()
        filled = int(float(o.get("filledQty") or o.get("tradedQuantity") or 0))
        price = o.get("price") or o.get("averageTradedPrice")
        try:
            price_f = float(price) if price is not None else 0.0
        except (TypeError, ValueError):
            price_f = 0.0
        orders.append(
            {
                "order_id": oid,
                "client_order_id": str(o.get("correlationId") or o.get("clientOrderId") or oid or ""),
                "broker_order_id": oid,
                "symbol": bits.get("tradingsymbol") or sym,
                "underlying": bits.get("underlying") or und,
                "expiry": bits.get("expiry"),
                "strike": bits.get("strike"),
                "option_type": bits.get("option_type"),
                "side": str(o.get("transactionType") or o.get("side") or "").upper(),
                "qty": qty,
                "lots": int(abs(qty) // lot_size) if lot_size else abs(qty),
                "lot_size": lot_size,
                "price": price_f,
                "average_price": float(o.get("averageTradedPrice") or 0),
                "filled_qty": filled,
                "filled_quantity": filled,
                "order_type": str(o.get("orderType") or "MARKET"),
                "state": status,
                "status": status,
                "pending_quantity": int(float(o.get("remainingQuantity") or o.get("pendingQuantity") or 0)),
                "placed_at": _to_utc_z(o.get("createTime") or o.get("updateTime")),
                "cancellable": st_u not in terminal,
                "tag": str(o.get("tag") or o.get("remarks") or ""),
                "updated_at": o.get("updateTime") or o.get("createTime"),
            }
        )
    return {
        "orders": orders,
        "count": len(orders),
        "snapshot_at": _utc_now(),
        "detail": None,
    }


def _dig_quote(node: Any) -> Dict[str, Optional[float]]:
    ltp = bid = ask = None
    if not isinstance(node, dict):
        return {"ltp": None, "bid": None, "ask": None}
    for k in ("last_price", "lastPrice", "LTP", "ltp", "close"):
        if node.get(k) is not None:
            try:
                ltp = float(node[k])
                break
            except (TypeError, ValueError):
                continue
    depth = node.get("depth") or node.get("marketDepth") or {}
    buys = depth.get("buy") or depth.get("bid") or []
    sells = depth.get("sell") or depth.get("ask") or []
    if buys and isinstance(buys[0], dict):
        try:
            bid = float(buys[0].get("price") or buys[0].get("Price") or 0) or None
        except (TypeError, ValueError, IndexError):
            bid = None
    if sells and isinstance(sells[0], dict):
        try:
            ask = float(sells[0].get("price") or sells[0].get("Price") or 0) or None
        except (TypeError, ValueError, IndexError):
            ask = None
    for k in ("bid", "best_bid", "bidPrice"):
        if bid is None and node.get(k) is not None:
            try:
                bid = float(node[k])
            except (TypeError, ValueError):
                pass
    for k in ("ask", "best_ask", "askPrice"):
        if ask is None and node.get(k) is not None:
            try:
                ask = float(node[k])
            except (TypeError, ValueError):
                pass
    return {"ltp": ltp, "bid": bid, "ask": ask}


def market_quote_option(security_id: str) -> Dict[str, Any]:
    sid = str(security_id)
    body = {SEGMENT_OPT: [int(sid) if sid.isdigit() else sid]}
    raw: Any = {}
    try:
        raw = _request("POST", "/marketfeed/quote", body, retries=2, sleep_s=0)
    except Exception:
        try:
            raw = _request("POST", "/marketfeed/ltp", body, retries=1, sleep_s=0)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(str(exc)) from exc
    node: Any = raw
    if isinstance(raw, dict):
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        for key in (SEGMENT_OPT, "NSE_FNO", sid):
            if isinstance(data, dict) and key in data:
                data = data[key]
        if isinstance(data, dict) and sid in data:
            node = data[sid]
        elif isinstance(data, dict) and sid.isdigit() and str(int(sid)) in data:
            node = data[str(int(sid))]
        else:
            node = data
    q = _dig_quote(node)
    ltp = q["ltp"]
    bid = q["bid"] if q["bid"] is not None else ltp
    ask = q["ask"] if q["ask"] is not None else ltp
    if ltp is None and bid is not None:
        ltp = bid
    if ltp is None:
        raise RuntimeError("quote missing last price")
    return {
        "ltp": ltp,
        "bid": bid if bid is not None else ltp,
        "ask": ask if ask is not None else ltp,
        "quoted_at": _utc_now(),
        "stale": False,
        "raw_keys": list(raw.keys()) if isinstance(raw, dict) else [],
    }


def available_cash() -> Optional[float]:
    try:
        fl = fund_limit()
        for k in ("availabelBalance", "availableBalance", "sodLimit", "withdrawableBalance"):
            if fl.get(k) is not None:
                return float(fl[k])
    except Exception:
        return None
    return None


# ---- write OMS (paper/live) ----

def place_order(
    *,
    security_id: str,
    exchange_segment: str = SEGMENT_OPT,
    transaction_type: str,  # BUY / SELL
    quantity: int,
    order_type: str = "MARKET",
    product_type: str = "INTRADAY",
    price: float = 0.0,
    tag: str = "edge-desk",
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    cid = correlation_id or f"ed-{uuid.uuid4().hex[:16]}"
    body = {
        "dhanClientId": credentials()[0],
        "correlationId": cid,
        "transactionType": transaction_type.upper(),
        "exchangeSegment": exchange_segment,
        "productType": product_type,
        "orderType": order_type,
        "validity": "DAY",
        "securityId": str(security_id),
        "quantity": int(quantity),
        "price": float(price),
        "disclosedQuantity": 0,
        "afterMarketOrder": False,
        "boProfitValue": 0,
        "boStopLossValue": 0,
        "drvExpiryDate": None,
        "drvOptionType": None,
        "drvStrikePrice": None,
    }
    raw = _request("POST", "/orders", body, sleep_s=0.2)
    return {"correlation_id": cid, "raw": raw, "tag": tag}


def cancel_order(order_id: str) -> Dict[str, Any]:
    raw = _request("DELETE", f"/orders/{order_id}", sleep_s=0.2)
    return {"order_id": order_id, "raw": raw}
