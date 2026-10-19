"""Client logins, Groww link, and one-edge fan-out. Paper runner is not touched."""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.brokers.groww.gateway import gateway
from app.client_store import connect, hash_password, open_seal, seal, verify_password

IST = timezone(timedelta(hours=5, minutes=30))
_NAME = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,79}$")
_MOBILE = re.compile(r"^[6-9]\d{9}$")


def is_client_role(role: str) -> bool:
    return (role or "").strip().lower() == "client"


def ensure_operator() -> None:
    email = (os.environ.get("DESK_OPERATOR_EMAIL") or "").strip().lower()
    password = os.environ.get("DESK_OPERATOR_PASSWORD") or ""
    if not email or not password:
        return
    with connect() as conn:
        row = conn.execute("SELECT email FROM clients WHERE email = ?", (email,)).fetchone()
        if row:
            return
        conn.execute(
            "INSERT INTO clients (email, password_hash, role) VALUES (?, ?, 'admin')",
            (email, hash_password(password)),
        )
        conn.commit()


def create_client(email: str, password: str, role: str = "client") -> None:
    role = "admin" if role == "admin" else "client"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO clients (email, password_hash, role)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET password_hash = excluded.password_hash, role = excluded.role
            """,
            (email.strip().lower(), hash_password(password), role),
        )
        conn.commit()


def set_wallet(email: str, funds_inr: float, margin_per_lot: float, max_lots: int = 10) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE clients SET sim_funds_inr = ?, margin_per_lot = ?, max_lots = ? WHERE email = ?",
            (funds_inr, margin_per_lot, max_lots, email.strip().lower()),
        )
        conn.commit()


def login(email: str, password: str) -> Optional[Dict[str, str]]:
    ensure_operator()
    key = email.strip().lower()
    with connect() as conn:
        row = conn.execute("SELECT email, password_hash, role, status FROM clients WHERE email = ?", (key,)).fetchone()
    if not row or row["status"] != "active" or not verify_password(password, row["password_hash"]):
        return None
    return {"email": row["email"], "role": row["role"]}


def register(email: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _check_register(body)
    _save_link(email, str(body["totp_token"]), str(body["totp_secret"]), str(body["full_name"]).strip(), str(body["mobile"]).strip())
    return me_live(email)


def link_groww(email: str, token: str, secret: str) -> Dict[str, Any]:
    if len(token.strip()) < 20 or len(secret.strip()) < 8:
        raise ValueError("Paste the Groww TOTP token and secret.")
    _save_link(email, token, secret, None, None)
    return me_live(email)


def set_auto(email: str, auto_mode: bool) -> Dict[str, Any]:
    with connect() as conn:
        conn.execute(
            "UPDATE clients SET auto_mode = ?, stopped = 0 WHERE email = ?",
            (1 if auto_mode else 0, email.strip().lower()),
        )
        conn.commit()
        if auto_mode:
            _accept_pending(conn, email.strip().lower(), "auto")
            conn.commit()
    return me_live(email)


def stop_orders(email: str) -> Dict[str, Any]:
    key = email.strip().lower()
    with connect() as conn:
        conn.execute("UPDATE clients SET stopped = 1 WHERE email = ?", (key,))
        conn.execute(
            """
            UPDATE client_orders SET state = 'skipped', decision = 'skipped', lots = 0
            WHERE email = ? AND state = 'pending'
            """,
            (key,),
        )
        conn.commit()
    return me_live(email)


def decide(email: str, edge_id: str, decision: str) -> Dict[str, Any]:
    if decision not in ("accept", "reject"):
        raise ValueError("decision must be accept or reject")
    key = email.strip().lower()
    with connect() as conn:
        row = conn.execute(
            "SELECT id, state FROM client_orders WHERE email = ? AND edge_id = ?",
            (key, edge_id),
        ).fetchone()
        if not row or row["state"] != "pending":
            raise ValueError("no pending edge")
        if decision == "reject":
            conn.execute(
                "UPDATE client_orders SET state = 'rejected', decision = 'rejected', lots = 0 WHERE id = ?",
                (row["id"],),
            )
        else:
            conn.execute("UPDATE clients SET stopped = 0 WHERE email = ?", (key,))
            _send(conn, key, int(row["id"]), "accepted")
        conn.commit()
    return me_live(email)


def notify_edge(
    edge_id: str,
    contract: str,
    side: str,
    underlying: str = "NIFTY",
    strike: float = 0,
    option_type: str = "CE",
) -> None:
    """One shared edge. Each linked client is sized on their own balance."""
    side = "sell" if str(side).lower() == "sell" else "buy"
    option_type = "PE" if str(option_type).upper() == "PE" else "CE"
    underlying = "BANKNIFTY" if str(underlying).upper() == "BANKNIFTY" else "NIFTY"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO edges (id, contract, side, underlying, strike, option_type, fired_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (edge_id, contract, side, underlying, strike, option_type, now),
        )
        clients = conn.execute(
            """
            SELECT c.email, c.auto_mode FROM clients c
            JOIN groww_links g ON g.email = c.email
            WHERE c.status = 'active' AND g.status = 'linked'
            """
        ).fetchall()
        for client in clients:
            conn.execute(
                """
                INSERT INTO client_orders (email, edge_id, state)
                VALUES (?, ?, 'pending')
                ON CONFLICT(email, edge_id) DO NOTHING
                """,
                (client["email"], edge_id),
            )
            if int(client["auto_mode"]):
                order = conn.execute(
                    "SELECT id, state FROM client_orders WHERE email = ? AND edge_id = ?",
                    (client["email"], edge_id),
                ).fetchone()
                if order and order["state"] == "pending":
                    _send(conn, client["email"], int(order["id"]), "auto")
        conn.commit()


def refresh_access(now: Optional[datetime] = None) -> Dict[str, int]:
    """Rebuild access tokens. A failure marks that client reconnect and leaves the others."""
    now = now or datetime.now(IST)
    ok_n = 0
    bad_n = 0
    with connect() as conn:
        rows = conn.execute(
            "SELECT email, totp_token_enc, totp_secret_enc FROM groww_links WHERE status = 'linked'"
        ).fetchall()
        for row in rows:
            try:
                _exchange(conn, row["email"], open_seal(row["totp_token_enc"]), open_seal(row["totp_secret_enc"]))
                ok_n += 1
            except Exception:
                conn.execute("UPDATE groww_links SET status = 'reconnect' WHERE email = ?", (row["email"],))
                bad_n += 1
        conn.commit()
    due = now.hour == 5 and now.minute >= 45
    return {"refreshed": ok_n, "reconnect": bad_n, "due": int(due)}


def me_live(email: str) -> Dict[str, Any]:
    key = email.strip().lower()
    with connect() as conn:
        client = conn.execute("SELECT * FROM clients WHERE email = ?", (key,)).fetchone()
        if not client:
            raise ValueError("This login is not on the desk yet.")
        link = conn.execute("SELECT * FROM groww_links WHERE email = ?", (key,)).fetchone()
        pending = conn.execute(
            """
            SELECT o.edge_id, e.contract, e.side FROM client_orders o
            JOIN edges e ON e.id = o.edge_id
            WHERE o.email = ? AND o.state = 'pending'
            ORDER BY o.id DESC LIMIT 1
            """,
            (key,),
        ).fetchone()
        last = conn.execute(
            """
            SELECT o.edge_id, e.contract, e.side, o.state, o.lots, o.funds_inr
            FROM client_orders o JOIN edges e ON e.id = o.edge_id
            WHERE o.email = ? AND o.state != 'pending'
            ORDER BY o.id DESC LIMIT 1
            """,
            (key,),
        ).fetchone()
    status = link["status"] if link else "unlinked"
    funds = _linked_funds(client, link) if status == "linked" else None
    margin = float(client["margin_per_lot"]) if status == "linked" else None
    return {
        "auto_mode": bool(client["auto_mode"]),
        "funds_inr": funds,
        "margin_per_lot_inr": margin,
        "max_lots": int(client["max_lots"]),
        "link": {
            "status": status,
            "groww_client_id": link["groww_client_id"] if link else None,
        },
        "pending_edge": _edge(pending) if pending else None,
        "last_order": _last(last) if last else None,
    }


def roster() -> list:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT c.email, c.auto_mode, c.sim_funds_inr, g.status AS link_status,
                   (
                     SELECT state FROM client_orders o
                     WHERE o.email = c.email ORDER BY o.id DESC LIMIT 1
                   ) AS last_state
            FROM clients c
            LEFT JOIN groww_links g ON g.email = c.email
            WHERE c.role = 'client'
            ORDER BY c.email
            """
        ).fetchall()
    return [
        {
            "email": row["email"],
            "auto_mode": bool(row["auto_mode"]),
            "link_status": row["link_status"] or "unlinked",
            "funds_inr": float(row["sim_funds_inr"]) if row["link_status"] == "linked" else None,
            "last_state": row["last_state"],
        }
        for row in rows
    ]


def positions_for(email: str) -> Dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT e.underlying, e.strike, e.option_type, e.side, o.lots
            FROM client_orders o JOIN edges e ON e.id = o.edge_id
            WHERE o.email = ? AND o.state = 'filled'
            """,
            (email.strip().lower(),),
        ).fetchall()
    return {
        "rows": [
            {
                "underlying": row["underlying"],
                "expiry": "",
                "strike": row["strike"],
                "option_type": row["option_type"],
                "side": "SHORT" if row["side"] == "sell" else "LONG",
                "lots": row["lots"] or 0,
            }
            for row in rows
        ]
    }


def orders_for(email: str) -> Dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT o.id, e.underlying, e.side, o.lots, o.state
            FROM client_orders o JOIN edges e ON e.id = o.edge_id
            WHERE o.email = ? AND o.state IN ('pending', 'sent')
            """,
            (email.strip().lower(),),
        ).fetchall()
    orders = [
        {
            "order_id": str(row["id"]),
            "underlying": row["underlying"],
            "side": "SELL" if row["side"] == "sell" else "BUY",
            "lots": row["lots"] or 0,
            "status": str(row["state"]).upper(),
        }
        for row in rows
    ]
    return {"orders": orders, "count": len(orders)}


def trades_for(email: str) -> Dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT e.underlying, e.contract, e.side, o.lots, o.state
            FROM client_orders o JOIN edges e ON e.id = o.edge_id
            WHERE o.email = ? AND o.state IN ('filled', 'rejected', 'skipped')
            """,
            (email.strip().lower(),),
        ).fetchall()
    trades = [
        {
            "underlying": row["underlying"],
            "symbol": row["contract"],
            "side": row["side"],
            "lots": row["lots"] or 0,
            "exit_reason": "open" if row["state"] == "filled" else row["state"],
            "net_pnl": None,
        }
        for row in rows
    ]
    return {"trades": trades, "trade_count": len(trades), "total_net_pnl": 0}


def _linked_funds(client: sqlite3.Row, link: sqlite3.Row) -> Optional[float]:
    fallback = float(client["sim_funds_inr"])
    if (os.environ.get("GROWW_MODE") or "local").strip().lower() != "live":
        return fallback
    try:
        return float(gateway().funds(open_seal(link["access_token_enc"]), fallback))
    except Exception:
        return None


def lots_from_funds(funds_inr: float, margin: float, max_lots: int) -> int:
    if margin <= 0 or max_lots < 1:
        return 0
    return min(max_lots, int(funds_inr // margin))


def _check_register(body: Dict[str, Any]) -> None:
    if body.get("live_confirmed") is not True:
        raise ValueError("Enter your name, mobile, and Groww key, and confirm live orders.")
    if not _NAME.match(str(body.get("full_name") or "").strip()):
        raise ValueError("Enter your name, mobile, and Groww key, and confirm live orders.")
    if not _MOBILE.match(str(body.get("mobile") or "").strip()):
        raise ValueError("Enter your name, mobile, and Groww key, and confirm live orders.")
    if len(str(body.get("totp_token") or "").strip()) < 20 or len(str(body.get("totp_secret") or "").strip()) < 8:
        raise ValueError("Enter your name, mobile, and Groww key, and confirm live orders.")


def _save_link(email: str, token: str, secret: str, name: Optional[str], mobile: Optional[str]) -> None:
    key = email.strip().lower()
    with connect() as conn:
        client = conn.execute("SELECT email FROM clients WHERE email = ?", (key,)).fetchone()
        if not client:
            raise ValueError("This login is not on the desk yet.")
        if name is not None and mobile is not None:
            conn.execute("UPDATE clients SET full_name = ?, mobile = ? WHERE email = ?", (name, mobile, key))
        try:
            access, client_id, expires = gateway().session(token.strip(), secret.strip())
            status = "linked"
            access_enc = seal(access)
        except Exception:
            status = "reconnect"
            client_id = ""
            expires = ""
            access_enc = ""
        conn.execute(
            """
            INSERT INTO groww_links (
              email, status, groww_client_id, totp_token_enc, totp_secret_enc, access_token_enc, access_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
              status = excluded.status,
              groww_client_id = excluded.groww_client_id,
              totp_token_enc = excluded.totp_token_enc,
              totp_secret_enc = excluded.totp_secret_enc,
              access_token_enc = excluded.access_token_enc,
              access_expires_at = excluded.access_expires_at
            """,
            (key, status, client_id, seal(token.strip()), seal(secret.strip()), access_enc, expires),
        )
        conn.commit()


def _accept_pending(conn: sqlite3.Connection, email: str, decision: str) -> None:
    rows = conn.execute(
        "SELECT id FROM client_orders WHERE email = ? AND state = 'pending'",
        (email,),
    ).fetchall()
    for row in rows:
        _send(conn, email, int(row["id"]), decision)


def _send(conn: sqlite3.Connection, email: str, order_id: int, decision: str) -> None:
    client = conn.execute("SELECT * FROM clients WHERE email = ?", (email,)).fetchone()
    link = conn.execute("SELECT * FROM groww_links WHERE email = ?", (email,)).fetchone()
    edge = conn.execute(
        """
        SELECT e.contract, e.side FROM client_orders o JOIN edges e ON e.id = o.edge_id WHERE o.id = ?
        """,
        (order_id,),
    ).fetchone()
    if not client or int(client["stopped"]) or not link or link["status"] != "linked" or not edge:
        conn.execute(
            "UPDATE client_orders SET state = 'skipped', decision = 'skipped', lots = 0 WHERE id = ?",
            (order_id,),
        )
        return
    try:
        access = open_seal(link["access_token_enc"])
        funds = float(gateway().funds(access, float(client["sim_funds_inr"])))
        lots = lots_from_funds(funds, float(client["margin_per_lot"]), int(client["max_lots"]))
    except Exception:
        conn.execute(
            "UPDATE client_orders SET state = 'rejected', decision = ?, funds_inr = NULL, lots = 0 WHERE id = ?",
            (decision, order_id),
        )
        return
    if lots < 1:
        conn.execute(
            """
            UPDATE client_orders SET state = 'skipped', decision = 'skipped', lots = 0, funds_inr = ?
            WHERE id = ?
            """,
            (funds, order_id),
        )
        return
    try:
        groww_id = gateway().place(access, edge["side"], edge["contract"], lots)
    except Exception:
        conn.execute(
            "UPDATE client_orders SET state = 'rejected', decision = ?, funds_inr = ?, lots = ? WHERE id = ?",
            (decision, funds, lots, order_id),
        )
        return
    conn.execute(
        """
        UPDATE clients SET sim_funds_inr = ? WHERE email = ?
        """,
        (funds, email),
    )
    conn.execute(
        """
        UPDATE client_orders
        SET state = 'filled', decision = ?, funds_inr = ?, lots = ?, groww_order_id = ?
        WHERE id = ?
        """,
        (decision, funds, lots, groww_id, order_id),
    )


def _exchange(conn: sqlite3.Connection, email: str, token: str, secret: str) -> None:
    access, client_id, expires = gateway().session(token, secret)
    conn.execute(
        """
        UPDATE groww_links
        SET status = 'linked', groww_client_id = ?, access_token_enc = ?, access_expires_at = ?
        WHERE email = ?
        """,
        (client_id, seal(access), expires, email),
    )


def _edge(row: sqlite3.Row) -> Dict[str, str]:
    return {"edge_id": row["edge_id"], "contract": row["contract"], "side": row["side"]}


def _last(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "edge_id": row["edge_id"],
        "contract": row["contract"],
        "side": row["side"],
        "state": row["state"],
        "lots": row["lots"],
        "funds_inr": row["funds_inr"],
    }
