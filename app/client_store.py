"""SQLite WAL store for client logins and Groww links. Secrets stay sealed."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sqlite3
from pathlib import Path
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
  email TEXT PRIMARY KEY,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  full_name TEXT NOT NULL DEFAULT '',
  mobile TEXT NOT NULL DEFAULT '',
  auto_mode INTEGER NOT NULL DEFAULT 0,
  stopped INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  max_lots INTEGER NOT NULL DEFAULT 10,
  sim_funds_inr REAL NOT NULL DEFAULT 180000,
  margin_per_lot REAL NOT NULL DEFAULT 52000
);
CREATE TABLE IF NOT EXISTS groww_links (
  email TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'unlinked',
  groww_client_id TEXT,
  totp_token_enc TEXT,
  totp_secret_enc TEXT,
  access_token_enc TEXT,
  access_expires_at TEXT
);
CREATE TABLE IF NOT EXISTS edges (
  id TEXT PRIMARY KEY,
  contract TEXT NOT NULL,
  side TEXT NOT NULL,
  underlying TEXT NOT NULL DEFAULT 'NIFTY',
  strike REAL NOT NULL DEFAULT 0,
  option_type TEXT NOT NULL DEFAULT 'CE',
  fired_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS client_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  decision TEXT,
  funds_inr REAL,
  lots INTEGER,
  groww_order_id TEXT,
  state TEXT NOT NULL,
  UNIQUE(email, edge_id)
);
"""


def db_path() -> Path:
    raw = (os.environ.get("CLIENT_LIVE_DB") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "data" / "client_live.sqlite"


def link_key() -> bytes:
    raw = (os.environ.get("GROWW_LINK_KEY") or "").strip()
    if not raw:
        path = db_path().parent / ".groww_link_key"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            raw = base64.b64encode(os.urandom(32)).decode()
            path.write_text(raw, encoding="utf-8")
    return hashlib.sha256(raw.encode("utf-8")).digest()


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt:" + salt.hex() + ":" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        _kind, salt_hex, digest_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
        expect = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest, expect)


def _stream(key: bytes, nonce: bytes, size: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < size:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:size]


def seal(plain: str) -> str:
    raw = plain.encode("utf-8")
    nonce = os.urandom(16)
    key = link_key()
    cipher = bytes(a ^ b for a, b in zip(raw, _stream(key, nonce, len(raw))))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return base64.b64encode(nonce + mac + cipher).decode("ascii")


def open_seal(packed: Optional[str]) -> str:
    if not packed:
        return ""
    blob = base64.b64decode(packed.encode("ascii"))
    nonce, mac, cipher = blob[:16], blob[16:48], blob[48:]
    key = link_key()
    expect = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expect):
        raise ValueError("sealed value failed")
    raw = bytes(a ^ b for a, b in zip(cipher, _stream(key, nonce, len(cipher))))
    return raw.decode("utf-8")
