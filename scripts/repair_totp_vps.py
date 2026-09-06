#!/usr/bin/env python3
"""Rewrite VPS desk .env from local secrets and mint token via TOTP."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PASS = os.environ["EDGE_VPS_PASS"]
KEY = os.environ.get("DESK_API_KEY", "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c=")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_local() -> dict[str, str]:
    merged: dict[str, str] = {}
    for p in (
        Path(r"D:\Options-Edge-Desk\.env"),
        Path(r"D:\Options-Nifty-Edge-Lab\.env"),
        Path(r"D:\Options-Edge-Lab\.env"),
    ):
        vals = parse_env(p)
        for k in ("DHAN_CLIENT_ID", "DHAN_PIN", "DHAN_TOTP_SECRET", "DESK_API_KEY"):
            if vals.get(k) and not merged.get(k):
                merged[k] = vals[k]
    return merged


def totp_code(secret: str) -> str:
    import base64
    import hashlib
    import hmac
    import struct
    import time

    key = secret.strip().replace(" ", "").upper()
    key += "=" * ((8 - len(key) % 8) % 8)
    raw = base64.b32decode(key, casefold=True)
    counter = int(time.time() // 30)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(raw, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def mint_local(client: str, pin: str, secret: str) -> str:
    totp = totp_code(secret)
    qs = urllib.parse.urlencode({"dhanClientId": client, "pin": pin, "totp": totp})
    url = f"https://auth.dhan.co/app/generateAccessToken?{qs}"
    req = urllib.request.Request(url, method="POST", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"generateAccessToken HTTP {e.code}: {body}") from e
    token = str(data.get("accessToken") or "")
    if not token:
        raise RuntimeError(f"no accessToken in response keys={list(data)}")
    print("local mint ok expiry=", data.get("expiryTime"), flush=True)
    return token


def run(c, cmd: str, timeout: int = 120) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    print(f"[{o.channel.recv_exit_status()}] {cmd}\n{out}\n---", flush=True)
    return out


def main() -> int:
    local = load_local()
    client = local.get("DHAN_CLIENT_ID") or ""
    pin = local.get("DHAN_PIN") or ""
    secret = local.get("DHAN_TOTP_SECRET") or ""
    if not (client and pin and secret):
        raise SystemExit("local CLIENT/PIN/TOTP missing")
    print(
        f"local ready client={client} pin_len={len(pin)} totp_len={len(secret)}",
        flush=True,
    )

    # mint on laptop first (proves credentials)
    token = mint_local(client, pin, secret)

    # also update local desk .env access token
    desk_env = Path(r"D:\Options-Edge-Desk\.env")
    vals = parse_env(desk_env)
    vals.update(
        {
            "DESK_API_KEY": KEY,
            "DHAN_CLIENT_ID": client,
            "DHAN_PIN": pin,
            "DHAN_TOTP_SECRET": secret,
            "DHAN_ACCESS_TOKEN": token,
            "DESK_MODE": "paper",
            "NIFTY_LAB_ROOT": vals.get("NIFTY_LAB_ROOT") or "D:/Options-Nifty-Edge-Lab",
            "BN_LAB_ROOT": vals.get("BN_LAB_ROOT") or "D:/Options-Edge-Lab",
            "NIFTY_CONFIG": vals.get("NIFTY_CONFIG")
            or "config/rungs/nifty_alpha.yaml",
            "BN_CONFIG": vals.get("BN_CONFIG") or "config/rungs/bn_alpha.yaml",
            "LIVE_NIFTY": "0",
            "LIVE_BANKNIFTY": "0",
        }
    )
    desk_env.write_text("\n".join(f"{k}={v}" for k, v in vals.items()) + "\n", encoding="utf-8")

    remote_vals = {
        "DESK_API_KEY": KEY,
        "DESK_MODE": "paper",
        "DHAN_CLIENT_ID": client,
        "DHAN_PIN": pin,
        "DHAN_TOTP_SECRET": secret,
        "DHAN_ACCESS_TOKEN": token,
        "NIFTY_LAB_ROOT": "/root/Options-Nifty-Edge-Lab",
        "BN_LAB_ROOT": "/root/Options-Edge-Lab",
        "NIFTY_CONFIG": "config/rungs/nifty_alpha.yaml",
        "BN_CONFIG": "config/rungs/bn_alpha.yaml",
        "LIVE_NIFTY": "0",
        "LIVE_BANKNIFTY": "0",
    }

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    sftp = c.open_sftp()
    remote = f"{CHROOT}{DESK}/.env"
    with sftp.file(remote, "w") as fh:
        for k, v in remote_vals.items():
            fh.write(f"{k}={v}\n")
    sftp.close()
    print("rewrote VPS .env via sftp", flush=True)

    run(c, "mountpoint -q /mnt/sys/proc || mount -t proc proc /mnt/sys/proc")
    run(c, "fuser -k 8080/tcp 2>/dev/null || true; sleep 1")
    run(
        c,
        f"nohup chroot {CHROOT} /bin/bash -c "
        f"'cd {DESK} && set -a && . {DESK}/.env && set +a && "
        f"export PYTHONPATH={DESK} && "
        f"exec /root/Options-Edge-Lab/.venv/bin/python3 -m uvicorn app.main:app "
        f"--host 127.0.0.1 --port 8080' "
        f"> {CHROOT}{DESK}/logs/desk.out 2>&1 & sleep 3; "
        f"curl -s http://127.0.0.1:8080/healthz; echo",
    )
    out = run(
        c,
        f"curl -s -H 'X-API-Key: {KEY}' http://127.0.0.1:8080/api/v1/desk/system/token",
    )
    c.close()
    if '"token_ok":true' in out or '"auto_totp_enabled":true' in out:
        print("SUCCESS", flush=True)
        return 0
    print("check output above", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
